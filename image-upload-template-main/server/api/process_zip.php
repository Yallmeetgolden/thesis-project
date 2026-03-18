<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/Bearer\s(\S+)/', $auth, $m)) {
    http_response_code(401);
    echo json_encode(['error' => 'No token']);
    exit;
}

$token = $m[1];
$parts = explode('.', $token);
if (count($parts) !== 3) {
    http_response_code(401);
    echo json_encode(['error' => 'Invalid token']);
    exit;
}

list($h, $p, $s) = $parts;
$signature = base64_decode(strtr($s, '-_', '+/'));
$valid = hash_hmac('sha256', "$h.$p", $JWT_SECRET, true) === $signature;
if (!$valid) {
    http_response_code(401);
    echo json_encode(['error' => 'Invalid token']);
    exit;
}

$payload = json_decode(base64_decode($p), true);
if (!isset($payload['exp']) || $payload['exp'] < time()) {
    http_response_code(401);
    echo json_encode(['error' => 'Expired']);
    exit;
}

$userId = $payload['sub'];
$sessionId = $_POST['sessionId'] ?? '';
$batchSize = isset($_POST['batchSize']) ? (int)$_POST['batchSize'] : 200;
if ($batchSize < 50) $batchSize = 50;
if ($batchSize > 1000) $batchSize = 1000;

if (!$sessionId || !preg_match('/^session_\d+$/', $sessionId)) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid sessionId']);
    exit;
}

$sessionDir = __DIR__ . '/../../uploads/user_' . $userId . '/' . $sessionId;
$statePath = $sessionDir . '/process_state.json';

if (!is_dir($sessionDir) || !file_exists($statePath)) {
    http_response_code(404);
    echo json_encode(['error' => 'Session not found']);
    exit;
}

$archiveMatches = glob($sessionDir . '/*.zip');
if (!$archiveMatches || !isset($archiveMatches[0])) {
    http_response_code(404);
    echo json_encode(['error' => 'Archive not found']);
    exit;
}
$archivePath = $archiveMatches[0];

$stateRaw = @file_get_contents($statePath);
$state = json_decode($stateRaw ?: '{}', true);
if (!is_array($state)) {
    $state = [];
}

if (($state['status'] ?? '') === 'done') {
    echo json_encode([
        'success' => true,
        'status' => 'done',
        'progress' => 100,
        'imageCount' => (int)($state['imageCount'] ?? 0),
        'processedEntries' => (int)($state['processedEntries'] ?? 0),
        'totalEntries' => (int)($state['totalEntries'] ?? 0),
        'sessionId' => $sessionId
    ]);
    exit;
}

if (!class_exists('ZipArchive')) {
    http_response_code(500);
    echo json_encode(['error' => 'ZIP support is not enabled on server']);
    exit;
}

$zip = new ZipArchive();
if ($zip->open($archivePath) !== true) {
    http_response_code(400);
    echo json_encode(['error' => 'Cannot open ZIP archive']);
    exit;
}

$imageExt = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'];
$maxImages = 20000;
$maxTotalUncompressed = 1024 * 1024 * 1024;

$totalEntries = (int)$zip->numFiles;
$nextIndex = (int)($state['nextIndex'] ?? 0);
$imageCount = (int)($state['imageCount'] ?? 0);
$totalUncompressed = (int)($state['totalUncompressed'] ?? 0);

$extractDir = $sessionDir . '/images';
if (!is_dir($extractDir)) {
    mkdir($extractDir, 0755, true);
}

$end = min($totalEntries, $nextIndex + $batchSize);
for ($i = $nextIndex; $i < $end; $i++) {
    $stat = $zip->statIndex($i);
    if (!$stat || !isset($stat['name'])) continue;

    $entryName = str_replace('\\', '/', $stat['name']);
    if (substr($entryName, -1) === '/') continue;
    if (strpos($entryName, '..') !== false || strpos($entryName, ':') !== false || substr($entryName, 0, 1) === '/') continue;

    $entryExt = strtolower(pathinfo($entryName, PATHINFO_EXTENSION));
    if (!in_array($entryExt, $imageExt, true)) continue;

    $entrySize = (int)($stat['size'] ?? 0);
    $totalUncompressed += $entrySize;
    if ($totalUncompressed > $maxTotalUncompressed) {
        $zip->close();
        $state['status'] = 'error';
        $state['error'] = 'ZIP uncompressed image content too large';
        $state['updatedAt'] = time();
        file_put_contents($statePath, json_encode($state));
        http_response_code(413);
        echo json_encode(['error' => $state['error']]);
        exit;
    }

    if ($imageCount >= $maxImages) {
        $zip->close();
        $state['status'] = 'error';
        $state['error'] = 'Too many images in ZIP';
        $state['updatedAt'] = time();
        file_put_contents($statePath, json_encode($state));
        http_response_code(413);
        echo json_encode(['error' => $state['error']]);
        exit;
    }

    $targetPath = $extractDir . '/' . $entryName;
    $targetFolder = dirname($targetPath);
    if (!is_dir($targetFolder)) {
        mkdir($targetFolder, 0755, true);
    }

    $in = $zip->getStream($stat['name']);
    if (!$in) continue;

    $out = fopen($targetPath, 'wb');
    if (!$out) {
        fclose($in);
        continue;
    }

    stream_copy_to_stream($in, $out);
    fclose($in);
    fclose($out);
    $imageCount++;
}

$zip->close();

$processedEntries = $end;
$done = $processedEntries >= $totalEntries;
$progress = $totalEntries > 0 ? (int)floor(($processedEntries / $totalEntries) * 100) : 100;

$state = [
    'status' => $done ? 'done' : 'processing',
    'sessionId' => $sessionId,
    'archiveName' => basename($archivePath),
    'totalEntries' => $totalEntries,
    'processedEntries' => $processedEntries,
    'imageCount' => $imageCount,
    'nextIndex' => $processedEntries,
    'totalUncompressed' => $totalUncompressed,
    'progress' => $progress,
    'error' => null,
    'updatedAt' => time()
];

file_put_contents($statePath, json_encode($state));

echo json_encode([
    'success' => true,
    'status' => $state['status'],
    'progress' => $state['progress'],
    'imageCount' => $state['imageCount'],
    'processedEntries' => $state['processedEntries'],
    'totalEntries' => $state['totalEntries'],
    'sessionId' => $sessionId
]);
