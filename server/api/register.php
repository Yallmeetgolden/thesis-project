<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

$body = json_decode(file_get_contents('php://input'), true);
$email = trim($body['email'] ?? '');
$pass = $body['password'] ?? '';

if (!filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($pass) < 6) {
    http_response_code(400);
    echo json_encode(['error'=>'Invalid input']);
    exit;
}

try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $db->prepare('INSERT INTO users (email, password) VALUES (:e, :p)');
    $hash = password_hash($pass, PASSWORD_DEFAULT);
    $stmt->execute([':e'=>$email, ':p'=>$hash]);
    echo json_encode(['ok'=>true]);
} catch (PDOException $e) {
    http_response_code(400);
    echo json_encode(['error'=>'Email already exists']);
}
