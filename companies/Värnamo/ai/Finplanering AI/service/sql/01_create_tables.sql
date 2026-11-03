/* ============================================================================
   AI Omplanering – resultattabeller
   Databas: BIzparc_Direct_VMO_AI      Motorversion: v4
   ----------------------------------------------------------------------------
   Två tabeller:

     tblAIAnglysisRun                 en rad per körning – policy, nyckeltal,
                                      status och eventuellt fel
     tblAIAnglysisGetAoColorCodeList  en rad per tillverkningsorder och körning

   Resultatet APPENDAS med en RunId per körning i stället för att skrivas över.
   Det ger körhistorik, gör två körningar jämförbara, och låter en misslyckad
   körning lämna föregående resultat orört. Vyn vwAIAnglysisSenaste längst ned
   ger alltid den senaste lyckade körningen.

   Kör hela skriptet en gång. Det är idempotent – befintliga objekt lämnas.
   ========================================================================= */

USE [BIzparc_Direct_VMO_AI];
GO

SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO

/* ---------------------------------------------------------------------------
   0. Styrtabell – handskakning mellan laddnings-SP:n och tjänsten

        Status = 0   SP:n klar. Källdatat är laddat, tjänsten får köra.
        Status = 1   Tjänsten klar. Väntar på att SP:n laddar ny data.

   Laddnings-SP:n avslutar med:

        UPDATE dbo.sysRunScript
        SET    Status = 0, SenastDTSPKor = GETDATE();

   Tjänsten sätter tillbaka Status = 1 först när resultatet ligger i
   databasen. Misslyckas körningen lämnas nollan kvar, så nästa poll (var
   5:e minut) gör om försöket på samma data.

   Tabellen ska innehålla exakt EN rad. Skriptet lägger in den om den saknas.
   ------------------------------------------------------------------------ */
IF OBJECT_ID(N'[dbo].[sysRunScript]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[sysRunScript](
        [Status]             [bit]      NULL,   -- 0: sp kör klar, 1: script kör klar
        [SenastDTSPKor]      [datetime] NULL,
        [SenastDTScriptKor]  [datetime] NULL
    ) ON [PRIMARY];
END
GO

-- Startläge: vila. Tjänsten kör inte förrän SP:n uttryckligen släpper fram den.
IF NOT EXISTS (SELECT 1 FROM [dbo].[sysRunScript])
    INSERT INTO [dbo].[sysRunScript] ([Status], [SenastDTSPKor], [SenastDTScriptKor])
    VALUES (1, NULL, NULL);
GO

/* ---------------------------------------------------------------------------
   1. Körlogg – en rad per körning
   ------------------------------------------------------------------------ */
IF OBJECT_ID(N'[dbo].[tblAIAnglysisRun]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[tblAIAnglysisRun](
        [RunId]                 [uniqueidentifier] NOT NULL,
        [RunStart]              [datetime]         NOT NULL,
        [RunEnd]                [datetime]             NULL,
        [DurationSeconds]       [decimal](9, 2)        NULL,
        [Status]                [nvarchar](20)     NOT NULL,   -- Startad / Klar / Fel
        [ErrorMessage]          [nvarchar](max)        NULL,
        [EngineVersion]         [nvarchar](20)     NOT NULL,
        [HostName]              [nvarchar](128)        NULL,

        -- Tidsreferens för frysningsregeln (2.1)
        [NowStockholm]          [datetime]         NOT NULL,

        -- Policy som körningen använde (2.3, 2.4)
        [ClusterWindowDays]     [int]              NOT NULL,
        [TardinessBudget]       [decimal](9, 4)    NOT NULL,
        [ProtectMarginDays]     [int]              NOT NULL,
        [GreenMarginDays]       [int]              NOT NULL,

        -- Population och frysning
        [RowsTotal]             [int]                  NULL,
        [RowsMovable]           [int]                  NULL,
        [FrozenStarted]         [int]                  NULL,
        [Machines]              [int]                  NULL,

        -- Status före/efter, bedömda med SAMMA statusgräns (2.4)
        [RedBefore]             [int]                  NULL,
        [RedAfter]              [int]                  NULL,
        [YellowBefore]          [int]                  NULL,
        [YellowAfter]           [int]                  NULL,
        [GreenBefore]           [int]                  NULL,
        [GreenAfter]            [int]                  NULL,

        -- Försening i dygn – visar om redan röda order blivit MER röda
        [LateDaysBefore]        [decimal](12, 1)       NULL,
        [LateDaysAfter]         [decimal](12, 1)       NULL,
        [LateDaysBeforeRed]     [decimal](12, 1)       NULL,
        [LateDaysAfterRed]      [decimal](12, 1)       NULL,
        [WorseCount]            [int]                  NULL,
        [WorstDays]             [decimal](9, 1)        NULL,
        [WorstAoNr]             [bigint]               NULL,

        -- Ställtid och ruttning
        [Clustered]             [int]                  NULL,
        [SetupHoursSaved]       [decimal](12, 2)       NULL,
        [PulledForward]         [int]                  NULL,
        [Rerouted]              [int]                  NULL,

        -- Datavalidering
        [WarningCount]          [int]                  NULL,
        [Warnings]              [nvarchar](max)        NULL,

        CONSTRAINT [PK_tblAIAnglysisRun] PRIMARY KEY CLUSTERED ([RunId] ASC)
    ) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY];

    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD CONSTRAINT [DF_tblAIAnglysisRun_RunId] DEFAULT (NEWID()) FOR [RunId];

    CREATE NONCLUSTERED INDEX [IX_tblAIAnglysisRun_RunStart]
        ON [dbo].[tblAIAnglysisRun] ([RunStart] DESC) INCLUDE ([Status]);
END
GO

/* ---------------------------------------------------------------------------
   1b. Tillägg – kolumner som tillkommit efter första driftsättningen.
   Säkra att köra flera gånger: varje kolumn läggs bara till om den saknas.
   Tjänsten fungerar även innan detta körts (saknade kolumner hoppas över
   och loggas), men då går det inte att se vilken enhet förseningen har.
   ------------------------------------------------------------------------ */

-- Enheten för LateDays*, WorstDays och ForseningDygn-kolumnerna, och vad
-- arbetsdagarna räknades mot: 'arbetsdagar/företag' (förval, samma för alla
-- order oavsett kalendernr), 'arbetsdagar/kal 7', 'arbetsdagar/egen' eller 'dygn'.
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'DelayUnit') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun] ADD [DelayUnit] [nvarchar](20) NULL;
GO

-- Satt bara när ett bestämt kalendernr användes; NULL för företagskalendern.
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'DelayCalendarNr') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun] ADD [DelayCalendarNr] [smallint] NULL;
GO

/* ---------------------------------------------------------------------------
   2. Resultatrader – en per tillverkningsorder och körning

   Kolumnerna följer mallens ordning från instruktionens avsnitt 5:
   nyckel -> Orginal_* (oförändrat från källan) -> AI_* (motorns förslag).
   Därefter härledda analyskolumner som gör tabellen användbar i Power BI
   utan att man behöver tolka fritexten i AI_Kommentar.
   ------------------------------------------------------------------------ */
IF OBJECT_ID(N'[dbo].[tblAIAnglysisGetAoColorCodeList]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[tblAIAnglysisGetAoColorCodeList](
        [AnalysisId]                [bigint] IDENTITY(1,1) NOT NULL,
        [RunId]                     [uniqueidentifier] NOT NULL,

        -- ----- Nyckel -----
        [AoNr]                      [bigint]           NULL,
        [AoPos]                     [int]              NULL,
        [OpNr]                      [int]              NULL,
        [ProdGr]                    [nvarchar](20)     NULL,
        [ArtNr]                     [nvarchar](60)     NULL,
        [AI_ProdGr]                 [nvarchar](20)     NULL,

        -- ----- Originalvärden, oförändrade från tblSTGetAoColorCodeList -----
        [Orginal_AoStartDatTid]     [datetime]         NULL,
        [Orginal_AoSlutDatTid]      [datetime]         NULL,
        [Orginal_TiSlutDat]         [datetime]         NULL,
        [Orginal_ColorCode]         [nvarchar](8)      NULL,
        [Orginal_ColorName]         [nvarchar](100)    NULL,
        [Orginal_OpkoPrioritet]     [int]              NULL,
        [Orginal_OrdBerLevDat]      [datetime]         NULL,

        -- ----- AI-värden -----
        [AI_AoStartDatTid]          [datetime]         NULL,
        [AI_AoSlutDatTid]           [datetime]         NULL,
        [AI_TiSlutDat]              [datetime]         NULL,
        [AI_ColorCode]              [nvarchar](8)      NULL,
        [AI_ColorName]              [nvarchar](100)    NULL,
        [AI_OpkoPrioritet]          [int]              NULL,
        [AI_LogCreatDateTime]       [datetime]         NOT NULL,
        [AI_Kommentar]              [nvarchar](max)    NULL,

        -- ----- Härledda analyskolumner -----
        -- Leveransmarginal i hela dygn: OrdBerLevDat - klartid.
        -- > GreenMarginDays = Grön, = Gul, < Röd  (instruktion 2.4)
        [Orginal_MarginalDygn]      [int]              NULL,
        [AI_MarginalDygn]           [int]              NULL,
        -- Försening i ARBETSDAGAR enligt skiftkalendern (tjänstens förval):
        -- antal arbetsdagar efter OrdBerLevDat t.o.m. klartiden. Helger och
        -- röda dagar räknas inte. Samma arbetsdagar för alla order oavsett
        -- kalendernr (tblAIAnglysisRun.DelayUnit). Skillnaden mellan kolumnerna visar om en redan
        -- försenad order blivit MER försenad av omplaneringen.
        -- OBS: MarginalDygn ovan är kalenderdygn och styr statusfärgen.
        [Orginal_ForseningDygn]     [int]              NULL,
        [AI_ForseningDygn]          [int]              NULL,
        -- Utgångsstatus bedömd med samma regel som AI_ColorName, så att
        -- före/efter går att jämföra utan att ett regelbyte ser ut som en
        -- försämring. Orginal_ColorName är Jeeves råa värde och rörs inte.
        [Orginal_ColorName_AIRegel] [nvarchar](100)    NULL,

        -- ----- Vad motorn gjorde med raden -----
        [AI_Fryst]                  [bit]              NOT NULL,
        [AI_FrysOrsak]              [nvarchar](60)     NULL,
        [AI_Omrutad]                [bit]              NOT NULL,
        [AI_OmrutadFran]            [nvarchar](20)     NULL,
        [AI_StalltidSparadH]        [float]            NULL,
        [AI_KlustradMotAoNr]        [bigint]           NULL,
        -- Ordern drogs fram förbi leveransdatumordningen för klustringens
        -- skull, och vad skadeprövningen bedömde att det kostade (2.3).
        [AI_Framdragen]             [bit]              NOT NULL,
        [AI_FramdragenKostnadDygn]  [decimal](9, 2)    NULL,

        CONSTRAINT [PK_tblAIAnglysisGetAoColorCodeList]
            PRIMARY KEY CLUSTERED ([AnalysisId] ASC),
        CONSTRAINT [FK_tblAIAnglysis_Run] FOREIGN KEY ([RunId])
            REFERENCES [dbo].[tblAIAnglysisRun] ([RunId]) ON DELETE CASCADE
    ) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY];

    ALTER TABLE [dbo].[tblAIAnglysisGetAoColorCodeList] ADD
        CONSTRAINT [DF_tblAIAnglysis_Fryst]      DEFAULT ((0)) FOR [AI_Fryst],
        CONSTRAINT [DF_tblAIAnglysis_Omrutad]    DEFAULT ((0)) FOR [AI_Omrutad],
        CONSTRAINT [DF_tblAIAnglysis_Framdragen] DEFAULT ((0)) FOR [AI_Framdragen];

    -- Uppslag på en order genom körhistoriken
    CREATE NONCLUSTERED INDEX [IX_tblAIAnglysis_AoNr]
        ON [dbo].[tblAIAnglysisGetAoColorCodeList] ([AoNr] ASC, [RunId] ASC);

    -- Körplanen per maskin: prioritet 100 först
    CREATE NONCLUSTERED INDEX [IX_tblAIAnglysis_Run_ProdGr]
        ON [dbo].[tblAIAnglysisGetAoColorCodeList]
           ([RunId] ASC, [AI_ProdGr] ASC, [AI_OpkoPrioritet] DESC);

    -- Plocka fram de röda ur en körning
    CREATE NONCLUSTERED INDEX [IX_tblAIAnglysis_Run_Color]
        ON [dbo].[tblAIAnglysisGetAoColorCodeList]
           ([RunId] ASC, [AI_ColorName] ASC)
        INCLUDE ([AoNr], [AI_ProdGr], [AI_TiSlutDat], [AI_MarginalDygn]);
END
GO

/* ---------------------------------------------------------------------------
   3. Vy: senaste lyckade körningen
   Använd denna i Power BI och i rapporter i stället för att filtrera på RunId.
   ------------------------------------------------------------------------ */
IF OBJECT_ID(N'[dbo].[vwAIAnglysisSenaste]', N'V') IS NOT NULL
    DROP VIEW [dbo].[vwAIAnglysisSenaste];
GO

CREATE VIEW [dbo].[vwAIAnglysisSenaste]
AS
SELECT  a.*
FROM    [dbo].[tblAIAnglysisGetAoColorCodeList] AS a
WHERE   a.[RunId] = (
            SELECT TOP (1) r.[RunId]
            FROM   [dbo].[tblAIAnglysisRun] AS r
            WHERE  r.[Status] = N'Klar'
            ORDER BY r.[RunStart] DESC
        );
GO

/* ---------------------------------------------------------------------------
   4. Städning – behåll de N senaste körningarna
   Anropas av tjänsten efter varje lyckad körning (RetentionRuns i config).
   ------------------------------------------------------------------------ */
IF OBJECT_ID(N'[dbo].[uspAIAnglysisPurge]', N'P') IS NOT NULL
    DROP PROCEDURE [dbo].[uspAIAnglysisPurge];
GO

CREATE PROCEDURE [dbo].[uspAIAnglysisPurge]
    @KeepRuns int = 30
AS
BEGIN
    SET NOCOUNT ON;

    -- Resultatraderna följer med via ON DELETE CASCADE.
    DELETE r
    FROM [dbo].[tblAIAnglysisRun] AS r
    WHERE r.[RunId] NOT IN (
        SELECT TOP (@KeepRuns) [RunId]
        FROM   [dbo].[tblAIAnglysisRun]
        ORDER BY [RunStart] DESC
    );

    RETURN @@ROWCOUNT;
END
GO
