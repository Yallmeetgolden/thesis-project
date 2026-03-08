// Firebase config using Vite env vars.
// Create a `.env.local` in the project root with the following values during development:
// VITE_FIREBASE_API_KEY=...
// VITE_FIREBASE_AUTH_DOMAIN=...
// VITE_FIREBASE_PROJECT_ID=...
// VITE_FIREBASE_STORAGE_BUCKET=...
// VITE_FIREBASE_MESSAGING_SENDER_ID=...
// VITE_FIREBASE_APP_ID=...

import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, GithubAuthProvider } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID
};

function isConfigured(cfg) {
  return cfg && typeof cfg.apiKey === 'string' && cfg.apiKey.length > 10;
}

let app = null;
let auth = null;
let googleProvider = null;
let githubProvider = null;

if (isConfigured(firebaseConfig)) {
  app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  googleProvider = new GoogleAuthProvider();
  githubProvider = new GithubAuthProvider();
} else {
  // Helpful console message for developers when env vars are missing
  // This avoids the confusing Firebase API key error and points to how to fix it.
  // Note: you still must provide the real config to authenticate.
  // See: https://console.firebase.google.com/ -> Project settings -> Your apps
  // Or create `.env.local` with VITE_FIREBASE_* values.
  // Example `.env.local` (do NOT commit this file):
  // VITE_FIREBASE_API_KEY=AIzaSy...
  // VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
  // ...
  console.error('Firebase not configured. Add VITE_FIREBASE_* env vars to .env.local. Authentication will be disabled until configured.');
}

export { auth, googleProvider, githubProvider };
export default app;
