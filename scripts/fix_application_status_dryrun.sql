-- =====================================================================
-- fix_application_status_dryrun.sql  (READ-ONLY preview)
-- Lists Notes-based candidates for individual review (section 5),
-- and the current Stage split. Run this BEFORE the write script.
--   sqlite3 -column data/applications.db < scripts/fix_application_status_dryrun.sql
-- =====================================================================

CREATE TEMP TABLE confirmed_detecon (
    url TEXT,
    company TEXT,
    applied_date TEXT
);
INSERT INTO confirmed_detecon VALUES (NULL, NULL, NULL);

.print === Current Stage split ===
SELECT Stage, COUNT(*) AS n FROM applications GROUP BY Stage;

.print
.print === Confirmed Detecon target(s) ===
SELECT id, URL,
       substr("Applied date",1,10) AS d,
       substr(Company,1,28)        AS company,
       substr(Role,1,34)           AS role,
       substr(Notes,1,70)          AS note_snippet
  FROM applications
 WHERE (
       URL = (SELECT url FROM confirmed_detecon)
    OR (
       Company = (SELECT company FROM confirmed_detecon)
       AND "Applied date" = (SELECT applied_date FROM confirmed_detecon)
    )
 )
 ORDER BY d DESC;

.print
.print === Notes candidates for individual review ONLY (no automatic status changes) ===
-- NOSONAR: Free-text substring searches require leading-wildcard matching; this
-- review-only scan has no conventional index that preserves the same semantics.
SELECT id, URL,
       substr("Applied date",1,10) AS d,
       substr(Company,1,28)        AS company,
       substr(Role,1,34)           AS role,
       substr(Notes,1,70)          AS note_snippet
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
   )
 ORDER BY d DESC;

.print
.print === Sanity: rows marked Rejected but with NO rejection note (possible false-closes to review) ===
SELECT substr("Applied date",1,10) AS d,
       substr(Company,1,28)        AS company,
       substr(Role,1,34)           AS role
  FROM applications
 WHERE Stage = 'Rejected'
     AND (Notes IS NULL OR Notes = '') -- NOSONAR: include NULL and empty Notes.
 ORDER BY d DESC;
