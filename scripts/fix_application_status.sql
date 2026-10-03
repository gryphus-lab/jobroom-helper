-- =====================================================================
-- fix_application_status.sql
-- Reconcile applications.Stage with ground truth (Job-Room / eServices /
-- recruiter emails). Run against ~/jobroom-helper/data/applications.db.
--
-- CONVENTION (locked):
--   Stage = 'Applied'   -> open / in-process
--   Stage = 'Rejected'  -> closed, no offer
--   (optional future)   -> 'Interview', 'Offer', 'Withdrawn'
--
-- USAGE:
--   cd ~/jobroom-helper
--   cp data/applications.db data/applications.db.bak_before_statusfix   # ALWAYS back up
--   sqlite3 data/applications.db < scripts/fix_application_status.sql
--
-- All statements are idempotent: re-running changes nothing already correct.
-- Every UPDATE matches on a stable key (prefer URL; fall back to Company+Applied date).
-- Edit the TEMPLATE blocks below with the real rejections/progressions, then run.
-- =====================================================================

-- Stop the sqlite3 CLI on a failed assertion; never continue after a rollback.
.bail on
BEGIN IMMEDIATE;

CREATE TEMP TABLE status_constants AS SELECT 'Rejected' AS rejected;

-- Replace NULL with the exact confirmed Detecon URL before running.
-- If there is no clean URL, use a unique Company + Applied date pair instead.
-- The target must exist exactly once; an unset or ambiguous target rolls back.
CREATE TEMP TABLE confirmed_detecon (
    url TEXT,
    company TEXT,
    applied_date TEXT
);
INSERT INTO confirmed_detecon VALUES (NULL, NULL, NULL);
CREATE TEMP TABLE status_assertion (
    valid INTEGER CONSTRAINT expected_single_detecon_row CHECK (valid = 1)
);
INSERT OR ROLLBACK INTO status_assertion
SELECT COUNT(*) = 1 FROM applications
 WHERE (
       URL = (SELECT url FROM confirmed_detecon)
    OR (
       Company = (SELECT company FROM confirmed_detecon)
       AND "Applied date" = (SELECT applied_date FROM confirmed_detecon)
    )
 );

-- A rerun may change zero rows only when this exact target is already rejected.
CREATE TEMP TABLE expected_detecon_changes AS
SELECT COUNT(*) AS n FROM applications
 WHERE (
       URL = (SELECT url FROM confirmed_detecon)
    OR (
       Company = (SELECT company FROM confirmed_detecon)
       AND "Applied date" = (SELECT applied_date FROM confirmed_detecon)
    )
 )
   AND Stage IS NOT (SELECT rejected FROM status_constants);

-- ---------------------------------------------------------------------
-- 0) SAFETY: show what will change is up to you (run the SELECTs in the
--    companion dry-run file first). Notes matches below are review-only.
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- 1) CONFIRMED rejections (already known from correspondence)
--    Detecon handled separately earlier; included here for idempotency.
-- ---------------------------------------------------------------------
UPDATE applications
   SET Stage = (SELECT rejected FROM status_constants),
       "Last Update Date" = '2026-10-02',
       "Update Details" = TRIM(COALESCE("Update Details",'') || ' | 02.10.2026 rejection confirmed'),
       updated_at = datetime('now')
 WHERE (
       URL = (SELECT url FROM confirmed_detecon)
    OR (
       Company = (SELECT company FROM confirmed_detecon)
       AND "Applied date" = (SELECT applied_date FROM confirmed_detecon)
    )
 )
   AND Stage IS NOT (SELECT rejected FROM status_constants);
INSERT OR ROLLBACK INTO status_assertion
SELECT changes() = (SELECT n FROM expected_detecon_changes);

-- ---------------------------------------------------------------------
-- 2) TEMPLATE — mark a specific application REJECTED by URL (preferred key)
--    Duplicate this block per rejection. Replace the URL and the date.
-- ---------------------------------------------------------------------
-- UPDATE applications
--    SET Stage = 'Rejected',
--        "Last Update Date" = '2026-10-02',
--        "Update Details" = TRIM(COALESCE("Update Details",'') || ' | rejected 2026-10-02'),
--        updated_at = datetime('now')
--  WHERE URL = 'PASTE_EXACT_URL_HERE'
--    AND Stage <> 'Rejected';

-- ---------------------------------------------------------------------
-- 3) TEMPLATE — mark REJECTED by Company + Applied date (when no clean URL)
--    Use when the row came from an NpA (npa:// surrogate URL).
-- ---------------------------------------------------------------------
-- UPDATE applications
--    SET Stage = 'Rejected',
--        "Last Update Date" = '2026-10-02',
--        "Update Details" = TRIM(COALESCE("Update Details",'') || ' | rejected 2026-10-02'),
--        updated_at = datetime('now')
--  WHERE Company = 'PASTE_COMPANY'
--    AND "Applied date" = 'YYYY-MM-DD'
--    AND Stage <> 'Rejected';

-- ---------------------------------------------------------------------
-- 4) TEMPLATE — reopen a row set to Rejected by mistake
-- ---------------------------------------------------------------------
-- UPDATE applications
--    SET Stage = 'Applied',
--        "Last Update Date" = '2026-10-02',
--        "Update Details" = TRIM(COALESCE("Update Details",'') || ' | reopened 2026-10-02'),
--        updated_at = datetime('now')
--  WHERE URL = 'PASTE_EXACT_URL_HERE'
--    AND Stage <> 'Applied';

-- ---------------------------------------------------------------------
-- 5) REVIEW ONLY — Notes phrases are ambiguous and never change Stage.
--    Verify each candidate individually, then use an exact-key template above.
-- NOSONAR: Free-text substring searches require leading-wildcard matching; this
-- review-only scan has no conventional index that preserves the same semantics.
-- ---------------------------------------------------------------------
SELECT id, URL, Company, Role, "Applied date", Stage, Notes
  FROM applications
 WHERE Stage = 'Applied'
   AND lower(COALESCE(Notes,'')) NOT LIKE '%duplicate%' -- NOSONAR
   AND (
         lower(Notes) LIKE '%we regret%' -- NOSONAR
      OR lower(Notes) LIKE '%not be proceeding%' -- NOSONAR
      OR lower(Notes) LIKE '%not be able to consider%' -- NOSONAR
      OR lower(Notes) LIKE '%unable to consider%' -- NOSONAR
      OR lower(Notes) LIKE '%not in a position to further%' -- NOSONAR
      OR lower(Notes) LIKE '%we will not%' -- NOSONAR
      OR lower(Notes) LIKE '%nicht weiter%' -- NOSONAR
      OR lower(Notes) LIKE '%leider%absage%' -- NOSONAR
      OR lower(Notes) LIKE '%eine absage%' -- NOSONAR
   );

DROP TABLE expected_detecon_changes;
DROP TABLE status_assertion;
DROP TABLE confirmed_detecon;
DROP TABLE status_constants;
COMMIT;

-- ---------------------------------------------------------------------
-- After completion, manually verify the Stage counts and inspect rows updated
-- on 2026-10-02.
-- ---------------------------------------------------------------------
