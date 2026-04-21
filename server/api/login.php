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

try {
    $db = new PDO('sqlite:' . $DB_PATH);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $db->prepare('SELECT id,password,email FROM users WHERE email=:e');
    $stmt->execute([':e'=>$email]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!$user || !password_verify($pass, $user['password'])) {
        http_response_code(401);
        echo json_encode(['error'=>'Invalid credentials']);
        exit;
    }

    // Simple JWT (HMAC-SHA256)
    $header = base64_encode(json_encode(['alg'=>'HS256','typ'=>'JWT']));
    $payload = base64_encode(json_encode(['sub'=>$user['id'],'email'=>$user['email'],'iat'=>time(),'exp'=>time()+3600]));
    $signature = hash_hmac('sha256', "$header.$payload", $JWT_SECRET, true);
    $sig_b64 = rtrim(strtr(base64_encode($signature), '+/', '-_'), '=');
    $jwt = "$header.$payload.$sig_b64";

    echo json_encode(['token'=>$jwt]);

} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['error'=>$e->getMessage()]);
}
