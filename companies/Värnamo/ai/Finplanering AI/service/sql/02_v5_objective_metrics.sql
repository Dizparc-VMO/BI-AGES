/* V5 objective metrics. Safe to run repeatedly. */

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'LockHorizonHours') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [LockHorizonHours] [smallint] NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'TardinessScoreBefore') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [TardinessScoreBefore] [decimal](14, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'TardinessScoreAfter') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [TardinessScoreAfter] [decimal](14, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'CapBreachCount') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [CapBreachCount] [int] NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'CapExcessDays') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [CapExcessDays] [decimal](12, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'WorstCapExcessDays') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [WorstCapExcessDays] [decimal](12, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisRun', N'UnplannedCount') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisRun]
        ADD [UnplannedCount] [int] NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'Orginal_TardinessScore') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisGetAoColorCodeList]
        ADD [Orginal_TardinessScore] [decimal](14, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'AI_TardinessScore') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisGetAoColorCodeList]
        ADD [AI_TardinessScore] [decimal](14, 3) NULL;
GO

IF COL_LENGTH(N'dbo.tblAIAnglysisGetAoColorCodeList', N'AI_CapExcessDygn') IS NULL
    ALTER TABLE [dbo].[tblAIAnglysisGetAoColorCodeList]
        ADD [AI_CapExcessDygn] [decimal](12, 3) NULL;
GO