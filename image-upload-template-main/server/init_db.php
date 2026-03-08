<?php
// Run this once to initialize the SQLite database and users table
require __DIR__ . '/config.php';

try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $db->exec("CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT
    );");
    echo "OK: DB initialized at $DB_PATH\n";
} catch (Exception $e) {
    echo "ERR: " . $e->getMessage();
}
