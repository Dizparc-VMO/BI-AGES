/*
    AI Omplanering V7: CustomerConfig och viktad planeringsspårning.
    Databas: BIzparc_Direct_VMO_AI

    Kör en gång före V7 SQL-tjänsten (skriptet är idempotent).
    CustomerConfig är en källtabell och fylls av kunddatans ordinarie laddning.
    Detta skript seedar eller ändrar inte affärsrader.
*/
USE [BIzparc_Direct_VMO_AI];
GO
SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO

/* Kundpolicy per kundorder. OrderNumber matchas i Python mot baslinjens OrderNr. */
IF OBJECT_ID(N'dbo.CustomerConfig', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CustomerConfig
    (
        OrderNumber nvarchar(100) NOT NULL,
        Customer nvarchar(100) NOT NULL,
        Vikt decimal(12,4) NOT NULL,
        MaxLate decimal(9,3) NULL,
        CONSTRAINT CK_CustomerConfig_Vikt_Positive CHECK (Vikt > 0),
        CONSTRAINT CK_CustomerConfig_MaxLate_Nonnegative CHECK (MaxLate IS NULL OR MaxLate >= 0)
    );
END;
GO

IF COL_LENGTH(N'dbo.CustomerConfig', N'OrderNumber') IS NULL
    THROW 51001, 'dbo.CustomerConfig saknar OrderNumber.', 1;
IF COL_LENGTH(N'dbo.CustomerConfig', N'Customer') IS NULL
    THROW 51002, 'dbo.CustomerConfig saknar Customer.', 1;
IF COL_LENGTH(N'dbo.CustomerConfig', N'Vikt') IS NULL
    THROW 51003, 'dbo.CustomerConfig saknar Vikt.', 1;
IF COL_LENGTH(N'dbo.CustomerConfig', N'MaxLate') IS NULL
    ALTER TABLE dbo.CustomerConfig ADD MaxLate decimal(9,3) NULL;
GO

IF EXISTS
(
    SELECT 1 FROM dbo.CustomerConfig
    WHERE OrderNumber IS NULL OR LTRIM(RTRIM(OrderNumber)) = N''
       OR Customer IS NULL OR LTRIM(RTRIM(Customer)) = N''
       OR Vikt IS NULL OR Vikt <= 0 OR MaxLate < 0
)
    THROW 51004, 'CustomerConfig innehåller tom order/kund, Vikt <= 0 eller MaxLate < 0.', 1;
GO

IF EXISTS
(
    SELECT LTRIM(RTRIM(OrderNumber))
    FROM dbo.CustomerConfig
    GROUP BY LTRIM(RTRIM(OrderNumber))
    HAVING COUNT(DISTINCT CONCAT(Customer, N'|', CONVERT(nvarchar(40), Vikt), N'|',
                                  COALESCE(CONVERT(nvarchar(40), MaxLate), N'<GLOBAL>'))) > 1
)
    THROW 51005, 'CustomerConfig har motstridig policy för samma OrderNumber.', 1;
GO

IF NOT EXISTS
(
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.CustomerConfig')
            AND name = N'IX_CustomerConfig_OrderNumber'
)
        CREATE INDEX IX_CustomerConfig_OrderNumber
        ON dbo.CustomerConfig(OrderNumber);
GO

/* Körningspolicy. Alla fält nullable för att historiska körningar ska bestå. */
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'MaxTardinessDays') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD MaxTardinessDays decimal(9,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'ScoreCutoffs') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD ScoreCutoffs nvarchar(200) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'ScoreRates') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD ScoreRates nvarchar(200) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'ScoreBandsJson') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD ScoreBandsJson nvarchar(max) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'GreenWeightBefore') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD GreenWeightBefore decimal(14,4) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'GreenWeightAfter') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD GreenWeightAfter decimal(14,4) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'BaselineOverLimitCount') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD BaselineOverLimitCount int NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'AfterOverLimitCount') IS NULL
    ALTER TABLE dbo.tblAIAnglysisRun ADD AfterOverLimitCount int NULL;
GO

/* Kundidentitet, använd policy och poäng per AO/position i resultatet. */
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'Orginal_TardinessScore') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD Orginal_TardinessScore decimal(14,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'AI_TardinessScore') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD AI_TardinessScore decimal(14,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'AI_CapExcessDygn') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD AI_CapExcessDygn decimal(12,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'CustomerOrderNumbers') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD CustomerOrderNumbers nvarchar(1000) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'CustomerNumbers') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD CustomerNumbers nvarchar(500) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'CustomerWeight') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD CustomerWeight decimal(12,4) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'MaxTardinessDays') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD MaxTardinessDays decimal(9,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'Orginal_WeightedTardinessScore') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD Orginal_WeightedTardinessScore decimal(14,3) NULL;
GO
IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'AI_WeightedTardinessScore') IS NULL
    ALTER TABLE dbo.tblAIAnglysisGetAoColorCodeList ADD AI_WeightedTardinessScore decimal(14,3) NULL;
GO

PRINT N'V7 CustomerConfig och policykolumner är klara. Kontrollera OrderNumber mot OrderNr innan tjänsten körs.';
GO
