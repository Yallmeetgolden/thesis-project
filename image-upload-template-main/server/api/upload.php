<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Credentials: true');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') exit;

require __DIR__ . '/../config.php';

// Verify token
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!preg_match('/Bearer\s(\S+)/', $auth, $m)) { 
    http_response_code(401); 
    echo json_encode(['error'=>'No token']); 
    exit; 
}

$token = $m[1];
$parts = explode('.', $token);
if (count($parts) !== 3) { 
    http_response_code(401); 
    echo json_encode(['error'=>'Invalid token']); 
    exit; 
}

list($h,$p,$s) = $parts;
$signature = base64_decode(strtr($s, '-_', '+/'));
$valid = hash_hmac('sha256', "$h.$p", $JWT_SECRET, true) === $signature;
if (!$valid) { 
    http_response_code(401); 
    echo json_encode(['error'=>'Invalid token']); 
    exit; 
}

$payload = json_decode(base64_decode($p), true);
if (!isset($payload['exp']) || $payload['exp'] < time()) { 
    http_response_code(401); 
    echo json_encode(['error'=>'Expired']); 
    exit; 
}

$userId = $payload['sub'];

// Create upload directory
$uploadDir = __DIR__ . '/../../uploads/user_' . $userId;
if (!is_dir($uploadDir)) {
    mkdir($uploadDir, 0755, true);
}

function removeDirRecursive($dir) {
    if (!is_dir($dir)) return;
    $items = scandir($dir);
    foreach ($items as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . DIRECTORY_SEPARATOR . $item;
        if (is_dir($path)) {
            removeDirRecursive($path);
        } else {
            @unlink($path);
        }
    }
    @rmdir($dir);
}

// Clear old uploads
foreach (glob($uploadDir . '/session_*', GLOB_ONLYDIR) as $dir) {
    removeDirRecursive($dir);
}

$sessionDir = $uploadDir . '/session_' . time();
mkdir($sessionDir, 0755, true);

$uploadedCount = 0;
$preview = null;

function isZipMime($tmpPath) {
    if (!function_exists('finfo_open')) return true;
    $finfo = finfo_open(FILEINFO_MIME_TYPE);
    if (!$finfo) return true;
    $mime = finfo_file($finfo, $tmpPath);
    finfo_close($finfo);
    return in_array($mime, ['application/zip', 'application/x-zip-compressed', 'multipart/x-zip']);
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['archive'])) {
    $archive = $_FILES['archive'];

    if (($archive['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
        http_response_code(400);
        echo json_encode(['error' => 'Archive upload failed']);
        exit;
    }

    $archiveName = $archive['name'] ?? '';
    $ext = strtolower(pathinfo($archiveName, PATHINFO_EXTENSION));
    if ($ext !== 'zip') {
        http_response_code(400);
        echo json_encode(['error' => 'Only .zip archives are allowed']);
        exit;
    }

    $tmpPath = $archive['tmp_name'];
    if (!isZipMime($tmpPath)) {
        http_response_code(400);
        echo json_encode(['error' => 'Invalid ZIP archive']);
        exit;
    }

    $maxZipBytes = 200 * 1024 * 1024;
    if (($archive['size'] ?? 0) > $maxZipBytes) {
        http_response_code(413);
        echo json_encode(['error' => 'ZIP archive is too large (max 200MB)']);
        exit;
    }

    $safeName = 'upload_' . date('Ymd_His') . '.zip';
    $archivePath = $sessionDir . '/' . $safeName;

    if (!move_uploaded_file($tmpPath, $archivePath)) {
        http_response_code(500);
        echo json_encode(['error' => 'Failed to store ZIP archive']);
        exit;
    }

    $sessionId = basename($sessionDir);
    $statePath = $sessionDir . '/process_state.json';
    file_put_contents($statePath, json_encode([
        'status' => 'pending',
        'sessionId' => $sessionId,
        'archiveName' => $safeName,
        'totalEntries' => 0,
        'processedEntries' => 0,
        'imageCount' => 0,
        'nextIndex' => 0,
        'progress' => 0,
        'error' => null,
        'updatedAt' => time()
    ]));

    echo json_encode([
        'success' => true,
        'mode' => 'archive',
        'uploadedCount' => 0,
        'imageCount' => 0,
        'preview' => null,
        'sessionId' => $sessionId,
        'archiveName' => $safeName,
        'archiveSize' => filesize($archivePath),
        'sessionDir' => $sessionDir
    ]);
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['files'])) {
    $files = $_FILES['files'];
    $imageExt = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'];
    
    $count = is_array($files['name']) ? count($files['name']) : 1;
    
    for ($i = 0; $i < $count; $i++) {
        $name = is_array($files['name']) ? $files['name'][$i] : $files['name'];
        $tmp = is_array($files['tmp_name']) ? $files['tmp_name'][$i] : $files['tmp_name'];
        $error = is_array($files['error']) ? $files['error'][$i] : $files['error'];
        
        if ($error !== UPLOAD_ERR_OK) continue;
        
        $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
        if (!in_array($ext, $imageExt)) continue;
        
        $safeName = basename($name);
        $path = $sessionDir . '/' . $safeName;
        if (move_uploaded_file($tmp, $path)) {
            $uploadedCount++;
            if ($preview === null) {
                $preview = 'data:image/jpeg;base64,' . base64_encode(file_get_contents($path));
            }
        }
    }
    
    echo json_encode([
        'success' => true,
        'uploadedCount' => $uploadedCount,
        'preview' => $preview,
        'sessionDir' => $sessionDir
    ]);
} else {
    http_response_code(400);
    echo json_encode(['error' => 'No files']);
}
?>
