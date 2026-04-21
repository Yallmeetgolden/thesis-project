<?php
// Simple router for PHP development server
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Routes for server/api/*
if (strpos($path, '/server/api/') === 0) {
    $file = __DIR__ . $path;
    if (file_exists($file) && is_file($file)) {
        require $file;
        return true;
    }
}

// Default: 404
http_response_code(404);
echo "Not found: $path";
return false;
?>
