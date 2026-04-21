<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

function fail($code, $message) {
    http_response_code($code);
    echo json_encode(['error' => $message]);
    exit;
}

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/Bearer\s(\S+)/', $auth, $m)) {
    fail(401, 'No token');
}

$token = $m[1];
$parts = explode('.', $token);
if (count($parts) !== 3) {
    fail(401, 'Invalid token');
}

list($h, $p, $s) = $parts;
$signature = base64_decode(strtr($s, '-_', '+/'));
$valid = hash_hmac('sha256', "$h.$p", $JWT_SECRET, true) === $signature;
if (!$valid) {
    fail(401, 'Invalid token');
}

$payload = json_decode(base64_decode($p), true);
if (!isset($payload['exp']) || $payload['exp'] < time()) {
    fail(401, 'Expired');
}

$userId = $payload['sub'];
$sessionId = $_POST['sessionId'] ?? '';
if (!$sessionId || !preg_match('/^session_\d+$/', $sessionId)) {
    fail(400, 'Invalid sessionId');
}

$qualityMode = $_POST['qualityMode'] ?? 'acceptable';
$validModes = ['very_blurry', 'slightly_blurry', 'acceptable', 'very_sharp'];
if (!in_array($qualityMode, $validModes, true)) {
    $qualityMode = 'acceptable';
}

$sessionDir = __DIR__ . '/../../uploads/user_' . $userId . '/' . $sessionId;
$imagesDir = $sessionDir . '/images';

if (!is_dir($imagesDir)) {
    fail(404, 'No extracted images found for this session');
}

if (!function_exists('curl_init')) {
    fail(500, 'cURL extension is not enabled on server');
}

set_time_limit(0);
$serviceUrl = getenv('BLUR_SERVICE_URL');
if (!$serviceUrl) {
    $serviceUrl = 'http://127.0.0.1:8001/analyze-folder';
}

$requestBody = json_encode([
    'imagesDir' => $imagesDir,
    'qualityMode' => $qualityMode,
    'useDeepLearning' => true,
    'deepLearningWeight' => 0.65
]);

$ch = curl_init($serviceUrl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $requestBody);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
curl_setopt($ch, CURLOPT_TIMEOUT, 600);

$responseBody = curl_exec($ch);
$curlErrNo = curl_errno($ch);
$curlErr = curl_error($ch);
$statusCode = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($curlErrNo !== 0) {
    fail(503, 'Blur analysis service is unavailable. Start Python service on http://127.0.0.1:8001. cURL: ' . $curlErr);
}

$serviceData = json_decode($responseBody ?: '', true);
if (!is_array($serviceData)) {
    fail(502, 'Blur analysis service returned invalid JSON');
}

if ($statusCode < 200 || $statusCode >= 300 || !($serviceData['success'] ?? false)) {
    $serviceErr = $serviceData['error'] ?? ('Blur analysis failed with status ' . $statusCode);
    fail(502, $serviceErr);
}

$serviceData['sessionId'] = $sessionId;
$serviceData['qualityMode'] = $qualityMode;
echo json_encode($serviceData);
?>