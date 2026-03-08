<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: http://localhost:5174');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/Bearer\s(\S+)/', $auth, $m)) { http_response_code(401); echo json_encode(['error'=>'No token']); exit; }
$token = $m[1];

// split token
$parts = explode('.', $token);
if (count($parts) !== 3) { http_response_code(401); echo json_encode(['error'=>'Invalid token']); exit; }
list($h,$p,$s) = $parts;
$signature = base64_decode(strtr($s, '-_', '+/'));
$valid = hash_hmac('sha256', "$h.$p", $JWT_SECRET, true) === $signature;
if (!$valid) { http_response_code(401); echo json_encode(['error'=>'Invalid token']); exit; }

$payload = json_decode(base64_decode($p), true);
if (!isset($payload['exp']) || $payload['exp'] < time()) { http_response_code(401); echo json_encode(['error'=>'Expired']); exit; }

echo json_encode(['id'=>$payload['sub'],'email'=>$payload['email']]);
