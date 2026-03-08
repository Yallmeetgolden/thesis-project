<?php
require __DIR__ . '/../server/config.php';
$email = $argv[1] ?? '';
$newpw = $argv[2] ?? '';
if (!$email || !$newpw) { echo "Usage: php scripts/reset_and_export.php email newpassword\n"; exit(1); }
try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    // Update password for the target user
    $hash = password_hash($newpw, PASSWORD_DEFAULT);
    $stmt = $db->prepare('UPDATE users SET password=:p WHERE email=:e');
    $stmt->execute([':p'=>$hash, ':e'=>$email]);
    echo "Updated password for: $email\n";

    // Ensure exports directory exists
    $outdir = __DIR__ . '/../exports';
    if (!is_dir($outdir)) mkdir($outdir, 0755, true);
    $outfile = $outdir . '/users_plain.csv';

    $fh = fopen($outfile, 'w');
    fputcsv($fh, ['id','email','plain_password','password_hash']);

    $q = $db->query('SELECT id,email,password FROM users');
    foreach ($q as $row) {
        $plain = ($row['email'] === $email) ? $newpw : '';
        fputcsv($fh, [$row['id'],$row['email'],$plain,$row['password']]);
    }
    fclose($fh);
    echo "Exported users to: $outfile\n";

} catch (Exception $e) {
    echo "ERR: " . $e->getMessage() . "\n";
}
