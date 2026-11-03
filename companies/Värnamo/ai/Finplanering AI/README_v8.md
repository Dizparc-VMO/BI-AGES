# AI Omplanering V8

V8 is the Windows desktop release of the V7 planning engine, with Excel and
SQL Server as selectable input sources. The calculation, customer weighting,
configurable tardiness limits, dynamic score bands, lock horizon, and output
contract remain version-isolated from V5–V7.

## Source modes

- **Excel:** choose a workbook and output directory, then run the plan.
- **SQL Server:** an administrator configures the server, database, SQL login,
  ODBC driver, source tables, and optional refresh procedure in the per-user
  `%APPDATA%\VarnamoFinplaneringAI\V8\connection.json` file. The operator enters
  only the SQL password in the UI. The password is held in memory for the
  session and is never written to either JSON settings file or logs.
- Saved planning parameters, score bands, and file paths are stored separately in
  `%APPDATA%\VarnamoFinplaneringAI\V8\settings.json`. They are saved with the
  **💾 Spara inställningar** button and automatically on connect, on run, and when
  the app closes. Each field is validated separately: an invalid field (for
  example an invalid score ladder) keeps its previously saved value while valid
  fields are saved, and the user is told which fields were not saved.
  **Återställ standardvärden** resets parameters and score bands (paths are kept).

## Score bands (Poängtrappa)

Days are signed relative to the delivery date: positive = late (rounded up),
negative = finished early (whole days toward zero). Days before the first row
use the first row's score, so a ladder starting at 0 scores early orders like
day 0. Rows must be ascending and contiguous (next `Från` = previous `Till` + 1),
day 0 must be included, only the last row has an empty `Till` (unbounded), and
every earliness row (`Till` < 0) must score lower than every row containing late
days. Earliness scores only influence sequencing; a free machine is never held
idle. Validation errors name the row, for example `Rad 7: …`. In the UI:

- **▲ / ▼** move a row; **−** removes a row; **+ Lägg till** splits the last row.
- **⇅ Sortera och rätta** sorts by `Från` and clears `Till` on the last row.
  Gaps, overlaps and too-high earliness scores are reported with row numbers
  rather than silently changed.

The SQL workflow is intentionally staged:

1. Connect and validate the configured SQL login.
2. Optionally run the administrator-configured refresh procedure. The app asks
   for confirmation before committing the procedure's changes.
3. Read the source tables and inspect any reported warnings.
4. Run the V8 plan and review the summary, preview, and locally generated
   `.xlsx`/`.csv` output.
5. Explicitly confirm before writing a new run and result rows to
   `dbo.tblAIAnglysisRun` and `dbo.tblAIAnglysisGetAoColorCodeList`.

The result write is transactional and appends a new `RunId`; it does not purge
or overwrite prior runs. No SQL writes happen merely by connecting, reading, or
calculating.

## SQL prerequisites and configuration

SQL mode requires Microsoft ODBC Driver 18 for SQL Server and the `pyodbc`
package embedded in the Windows build. The ODBC driver is a separate Microsoft
prerequisite and is not redistributed by this project. Excel mode does not
require a SQL driver.

On first start, V8 creates the per-user `connection.json` with the following
company-specific defaults supplied by the solution owner:

```json
{
  "server_name": "tcp:AHO-APP12,1433",
  "database": "BIzparc_Direct_VMO_AI",
  "username": "imad01",
  "odbc_driver": "ODBC Driver 18 for SQL Server",
  "encrypt": "yes",
  "trust_server_certificate": "yes",
  "connection_timeout": 25,
  "query_timeout": 300,
  "refresh_procedure": "dbo.sp_Fill_All_Tables",
  "refresh_parameters": [],
  "refresh_timeout": 0
}
```

Existing local configuration files are never overwritten by these defaults.
Keys missing from an existing file (for example `refresh_timeout` in files
created by earlier builds) receive the default value.
Administrators must review the login, target, procedure permissions, and timeout
for each installation. No password is included; the operator enters it at runtime.
`encrypt: yes` with `trust_server_certificate: yes` encrypts the connection but
skips verification of the server certificate and identity. This requested
compatibility default is not a substitute for a trusted certificate chain.
Once server certificates are configured correctly, use
`trust_server_certificate: no` in the local configuration.

The optional procedure must be a two-part `schema.procedure` identifier.
Its parameter names are validated and parameter values are bound, not
interpolated into SQL. The default procedure has no configured parameters;
verify that it can run without mandatory arguments, or adjust the local file.

### Procedure waiting, cancel, messages, and timeout

`refresh_timeout` applies only to the refresh procedure; reading and result
writing keep using `query_timeout`. With `refresh_timeout: 0` (default) the app
waits until SQL Server responds, however long the procedure takes. A positive
value is an explicit limit in seconds. The timeout is set on the connection
before the procedure cursor is created and restored afterwards.

During SQL work the SQL panel shows an indeterminate progress bar. The refresh
step displays its phase, elapsed time, and the timeout in effect.
The bar indicates that the app is waiting for SQL, not that the database is
making measurable progress. Completion is reported only after commit returns;
rollback also remains a waiting phase. Source snapshots and pending plans are
invalidated as soon as a refresh starts, including when it fails.

**■ Avbryt procedur** is enabled only while the procedure runs. After
confirmation the app calls `cursor.cancel()` and rolls back. Work committed
internally by the procedure before the cancel cannot be rolled back by the app;
verify it in SQL before rerunning. Cancels are reported separately from timeouts.

SQL `PRINT` and informational messages exposed by `pyodbc.cursor.messages` are
written to the run log after `execute` and `nextset` return, including messages
available on error. Delivery is buffered and not live: messages appear when the
procedure responds. A procedure that does not emit messages cannot provide
step-by-step progress. No server session polling or percentage estimate is performed.

`HYT00`/`HYT01` means the driver's SQL call timed out (only possible when
`refresh_timeout` > 0, or for reads/writes via `query_timeout`). The app attempts
rollback and does not retry automatically. Verify server sessions, blocking, and
any internal commits or external side effects before rerunning. To let the
procedure run to completion, set `refresh_timeout` to `0` in the local JSON and
restart the app. Do not put sensitive data in procedure messages: these are
displayed in the log.

The destination tables must already exist and match the V8/V7 result contract.
Review the V8 SQL sink and existing V7 table DDL before enabling write access.
Use a least-privilege login that can read required source tables and, only when
authorized, execute the refresh procedure and insert into the two result tables.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m pip install pyodbc
python omplanering_app_v8.py
```

To run focused checks:

```powershell
python -m unittest test_omplanering_v8 -v
python -m unittest test_omplanering_v7 -v
```

## Build and release on Windows

Install the dependencies from `requirements-build-v8.txt`, install Inno Setup
6, and run these commands from this directory:

```powershell
python -m pip install -r requirements-build-v8.txt
pyinstaller --noconfirm --clean packaging\finplanering_v8.spec
$env:APP_VERSION = "8.0.0"
iscc packaging\finplanering_v8.iss
```

The installer is written to `dist\AI-Omplanering-V8-Setup.exe`. The build bundles
`documentation_v8.html` (user, IT, and process documentation), `instuktion.md`
(solution specification and planning logic, linked from the documentation), and
this README. The
[`release-v8.yml`](../../../../.github/workflows/release-v8.yml) workflow is
started manually from GitHub Actions; it does not need a Git tag or create a
GitHub Release. Enter the installer version when starting the workflow. After
the run completes, download `AI-Omplanering-V8-Setup-<version>` from the run's
Artifacts section. GitHub retains this artifact for 30 days, and access follows
repository permissions. GitHub Pages is not used to distribute the executable.

The app uses `%APPDATA%` for user settings so upgrades do not overwrite them.
Uninstalling the app does not remove the user's SQL configuration or saved
planning parameters.
