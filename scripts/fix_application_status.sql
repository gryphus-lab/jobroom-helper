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

BEGIN TRANSACTION;

-- ---------------------------------------------------------------------
-- 0) SAFETY: show what will change is up to you (run the SELECTs in the
--    companion dry-run file first). This script only writes.
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- 1) CONFIRMED rejections (already known from correspondence)
--    Detecon handled separately earlier; included here for idempotency.
-- ---------------------------------------------------------------------
UPDATE applications
   SET Stage = 'Rejected',
       "Last Update Date" = '2026-10-02',
       "Update Details" = TRIM(COALESCE("Update Details",'') || ' | 02.10.2026 rejection confirmed'),
       updated_at = datetime('now')
 WHERE Company LIKE 'Detecon%'
   AND Stage <> 'Rejected';

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
-- 5) HYGIENE — auto-flag any row whose Notes clearly state a rejection
--    but Stage is still 'Applied'. Conservative keyword set (EN + DE).
--    The BCG duplicate note contains the word "DUPLICATE"/"no Absage" and
--    is explicitly EXCLUDED so it stays 'Applied' as it appears in the NpA.
-- ---------------------------------------------------------------------
UPDATE applications
   SET Stage = 'Rejected',
       "Last Update Date" = '2026-10-02',
       "Update Details" = TRIM(COALESCE("Update Details",'') || ' | auto-set Rejected from Notes 2026-10-02'),
       updated_at = datetime('now')
 WHERE Stage = 'Applied'
   AND lower(COALESCE(Notes,'')) NOT LIKE '%duplicate%'
   AND (
         lower(Notes) LIKE '%we regret%'
      OR lower(Notes) LIKE '%unfortunately%'
      OR lower(Notes) LIKE '%not be proceeding%'
      OR lower(Notes) LIKE '%not be able to consider%'
      OR lower(Notes) LIKE '%unable to consider%'
      OR lower(Notes) LIKE '%not in a position to further%'
      OR lower(Notes) LIKE '%we will not%'
      OR lower(Notes) LIKE '%nicht weiter%'
      OR lower(Notes) LIKE '%leider%absage%'
      OR lower(Notes) LIKE '%eine absage%'
   );

COMMIT;

-- ---------------------------------------------------------------------
-- POST-RUN verification (run manually):
--   SELECT Stage, COUNT(*) FROM applications GROUP BY Stage;
--   SELECT Company, Role, Stage, "Last Update Date"
--     FROM applications WHERE "Last Update Date" = '2026-10-02' ORDER BY Company;
-- ---------------------------------------------------------------------
