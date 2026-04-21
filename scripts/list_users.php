<?php
require __DIR__ . '/../server/config.php';
try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $db->query('SELECT id, email, password FROM users');
    foreach ($stmt as $row) {
        echo "{$row['id']} {$row['email']} {$row['password']}\n";
    }
} catch (Exception $e) {
    echo "ERR: " . $e->getMessage() . "\n";
}
