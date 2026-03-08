<?php
// Server configuration for PHP auth
// Change $JWT_SECRET to a strong random string in production
// IMPORTANT: replace these values with real credentials before using OAuth in production
$JWT_SECRET = 'CHANGE_ME_TO_A_LONG_RANDOM_SECRET_please_replace';
$DB_PATH = __DIR__ . "/../data/users.sqlite";

// Note: OAuth has been removed in this simplified setup.
// Keep $JWT_SECRET secure and replace it with a long random secret before production.

// Ensure data directory exists
if (!file_exists(dirname($DB_PATH))) {
    mkdir(dirname($DB_PATH), 0755, true);
}

?>
