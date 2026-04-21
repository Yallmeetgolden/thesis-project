<?php
require __DIR__ . '/../server/config.php';
$email = $argv[1] ?? '';
$pw = $argv[2] ?? '';
if (!$email || !$pw) { echo "Usage: php scripts/check_password.php email password\n"; exit(1); }
try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $db->prepare('SELECT password FROM users WHERE email=:e');
    $stmt->execute([':e'=>$email]);
    $h = $stmt->fetchColumn();
    if (!$h) { echo "No such user\n"; exit(1); }
    echo password_verify($pw, $h) ? "MATCH\n" : "NO MATCH\n";
} catch (Exception $e) {
    echo "ERR: " . $e->getMessage() . "\n";
}
