<?php
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

function fail_json($code, $message) {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode(['error' => $message]);
    exit;
}

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/Bearer\s(\S+)/', $auth, $m)) {
    fail_json(401, 'No token');
}

$token = $m[1];
$parts = explode('.', $token);
if (count($parts) !== 3) {
    fail_json(401, 'Invalid token');
}

list($h, $p, $s) = $parts;
$signature = base64_decode(strtr($s, '-_', '+/'));
$valid = hash_hmac('sha256', "$h.$p", $JWT_SECRET, true) === $signature;
if (!$valid) {
    fail_json(401, 'Invalid token');
}

$payload = json_decode(base64_decode($p), true);
if (!isset($payload['exp']) || $payload['exp'] < time()) {
    fail_json(401, 'Expired');
}

$userId = $payload['sub'];
$sessionId = $_POST['sessionId'] ?? '';
if (!$sessionId || !preg_match('/^session_\d+$/', $sessionId)) {
    fail_json(400, 'Invalid sessionId');
}

$selectedFilesRaw = $_POST['selectedFiles'] ?? '';
$selectedFiles = json_decode($selectedFilesRaw, true);
if (!is_array($selectedFiles) || count($selectedFiles) === 0) {
    fail_json(400, 'selectedFiles is required');
}

$sessionDir = __DIR__ . '/../../uploads/user_' . $userId . '/' . $sessionId;
$imagesDir = $sessionDir . '/images';
if (!is_dir($imagesDir)) {
    fail_json(404, 'No extracted images found for this session');
}

$imagesDirReal = realpath($imagesDir);
if ($imagesDirReal === false) {
    fail_json(500, 'Invalid images directory');
}

if (!class_exists('ZipArchive')) {
    fail_json(500, 'ZIP support is not enabled on server');
}

$tmpZipPath = tempnam(sys_get_temp_dir(), 'sel_zip_');
if ($tmpZipPath === false) {
    fail_json(500, 'Failed to create temporary export file');
}

$zipPath = $tmpZipPath . '.zip';
@unlink($tmpZipPath);

$zip = new ZipArchive();
if ($zip->open($zipPath, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
    fail_json(500, 'Failed to create export ZIP');
}

$added = 0;
$seen = [];
foreach ($selectedFiles as $relName) {
    if (!is_string($relName) || $relName === '') continue;
    if (isset($seen[$relName])) continue;
    $seen[$relName] = true;

    $normalized = str_replace('\\', '/', $relName);
    if (strpos($normalized, '..') !== false || strpos($normalized, ':') !== false || substr($normalized, 0, 1) === '/') {
        continue;
    }

    $fullPath = realpath($imagesDirReal . DIRECTORY_SEPARATOR . str_replace('/', DIRECTORY_SEPARATOR, $normalized));
    if ($fullPath === false || !is_file($fullPath)) {
        continue;
    }

    $fullPathNorm = str_replace('\\', '/', $fullPath);
    $imagesDirNorm = str_replace('\\', '/', $imagesDirReal);
    if (strpos($fullPathNorm, $imagesDirNorm . '/') !== 0) {
        continue;
    }

    if ($zip->addFile($fullPath, $normalized)) {
        $added++;
    }
}

$zip->close();

if ($added === 0) {
    @unlink($zipPath);
    fail_json(400, 'No valid files to export');
}

$downloadName = 'selected_top_' . $sessionId . '.zip';
header('Content-Type: application/zip');
header('Content-Disposition: attachment; filename="' . $downloadName . '"');
header('Content-Length: ' . filesize($zipPath));
header('Pragma: no-cache');
header('Expires: 0');

readfile($zipPath);
@unlink($zipPath);
exit;
?>