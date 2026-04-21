<?php
require __DIR__ . '/../server/config.php';

// Simple passwords for each registered user (for development/testing only)
$userPasswords = [
    'ezejioforemmanuel04@gmail.com' => 'password123'
];

try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Get all users from database
    $stmt = $db->query('SELECT id, email FROM users ORDER BY id');
    $users = $stmt->fetchAll(PDO::FETCH_ASSOC);
    
    // Prepare output directory
    $outdir = __DIR__ . '/../exports';
    if (!is_dir($outdir)) mkdir($outdir, 0755, true);
    $outfile = $outdir . '/all_users_passwords.csv';
    
    // Write CSV with plain passwords
    $fh = fopen($outfile, 'w');
    fputcsv($fh, ['ID', 'Email', 'Plain Password']);
    
    foreach ($users as $user) {
        $email = $user['email'];
        $plainPassword = isset($userPasswords[$email]) ? $userPasswords[$email] : '[PASSWORD UNKNOWN - Please reset]';
        fputcsv($fh, [$user['id'], $email, $plainPassword], ',', '"');
    }
    fclose($fh);
    
    echo "✓ Exported plain passwords to: $outfile\n";
    echo "Content:\n";
    echo file_get_contents($outfile);
    
} catch (Exception $e) {
    echo "ERR: " . $e->getMessage() . "\n";
}
?>
