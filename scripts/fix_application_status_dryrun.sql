-- =====================================================================
-- fix_application_status_dryrun.sql  (READ-ONLY preview)
-- Shows exactly which rows the auto-flag (section 5) would set to Rejected,
-- and the current Stage split. Run this BEFORE the write script.
--   sqlite3 -column data/applications.db < scripts/fix_application_status_dryrun.sql
-- =====================================================================

.print === Current Stage split ===
SELECT Stage, COUNT(*) AS n FROM applications GROUP BY Stage;

.print
.print === Rows section-5 auto-flag WOULD mark Rejected (Notes say rejected, Stage still Applied, excl. DUPLICATE) ===
SELECT substr("Applied date",1,10) AS d,
       substr(Company,1,28)        AS company,
       substr(Role,1,34)           AS role,
       substr(Notes,1,70)          AS note_snippet
  FROM applications
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
   )
 ORDER BY d DESC;

.print
.print === Sanity: rows marked Rejected but with NO rejection note (possible false-closes to review) ===
SELECT substr("Applied date",1,10) AS d,
       substr(Company,1,28)        AS company,
       substr(Role,1,34)           AS role
  FROM applications
 WHERE Stage = 'Rejected'
   AND COALESCE(Notes,'') = ''
 ORDER BY d DESC;
