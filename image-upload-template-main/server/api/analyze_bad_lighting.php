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

$sessionDir = __DIR__ . '/../../uploads/user_' . $userId . '/' . $sessionId;
$imagesDir = $sessionDir . '/images';

if (!is_dir($imagesDir)) {
    fail(404, 'No extracted images found for this session');
}

$pythonBin = getenv('PYTHON_BIN');
if (!$pythonBin) {
    $pythonBin = 'python';
}

$scriptPath = realpath(__DIR__ . '/../../python_service/bad_lighting_analyzer.py');
if (!$scriptPath || !file_exists($scriptPath)) {
    fail(500, 'Bad lighting analyzer script not found');
}

set_time_limit(0);
$minBrightness = (!empty($_POST['minBrightness']) ? (float)$_POST['minBrightness'] : 50.0);
$maxBrightness = (!empty($_POST['maxBrightness']) ? (float)$_POST['maxBrightness'] : 200.0);
$minContrast = (!empty($_POST['minContrast']) ? (float)$_POST['minContrast'] : 40.0);
$balanceThreshold = (!empty($_POST['balanceThreshold']) ? (float)$_POST['balanceThreshold'] : 40.0);
$maxBalanceRatio = (!empty($_POST['maxBalanceRatio']) ? (float)$_POST['maxBalanceRatio'] : 0.95);

$cmd = escapeshellcmd($pythonBin)
    . ' ' . escapeshellarg($scriptPath)
    . ' --imagesDir ' . escapeshellarg($imagesDir)
    . ' --minBrightness ' . escapeshellarg((string)$minBrightness)
    . ' --maxBrightness ' . escapeshellarg((string)$maxBrightness)
    . ' --minContrast ' . escapeshellarg((string)$minContrast)
    . ' --balanceThreshold ' . escapeshellarg((string)$balanceThreshold)
    . ' --maxBalanceRatio ' . escapeshellarg((string)$maxBalanceRatio);

$descriptorspec = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w']
];

$process = proc_open($cmd, $descriptorspec, $pipes, dirname(__DIR__, 2));
if (!is_resource($process)) {
    fail(500, 'Failed to launch bad lighting analyzer process');
}

fclose($pipes[0]);
$stdout = stream_get_contents($pipes[1]);
$stderr = stream_get_contents($pipes[2]);
fclose($pipes[1]);
fclose($pipes[2]);
$exitCode = proc_close($process);

if ($exitCode !== 0) {
    $detail = trim($stderr ?: $stdout);
    fail(502, 'Lighting analysis failed. ' . ($detail !== '' ? $detail : 'No error detail from process'));
}

$data = json_decode($stdout ?: '', true);
if (!is_array($data)) {
    fail(502, 'Bad lighting analyzer returned invalid JSON');
}

if (!($data['success'] ?? false)) {
    $msg = $data['error'] ?? 'Unknown lighting analysis error';
    fail(502, $msg);
}

$data['sessionId'] = $sessionId;
echo json_encode($data);
?>
