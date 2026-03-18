import React, { createContext, useContext, useEffect, useState } from "react";

const AuthContext = createContext();

export function useAuth() {
  return useContext(AuthContext);
}

// The PHP API will run on port 8000 under /server/api when using php -S
const API_BASE = 'http://127.0.0.1:8000/server/api';

function storeToken(token) {
  if (token) localStorage.setItem('auth_token', token);
  else localStorage.removeItem('auth_token');
}

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [loading, setLoading] = useState(true);

  async function fetchCurrentUser() {
    const token = localStorage.getItem('auth_token');
    if (!token) { setCurrentUser(null); setLoading(false); return; }
    try {
      const res = await fetch(API_BASE + '/user.php', { headers: { Authorization: 'Bearer ' + token } });
      if (!res.ok) throw new Error('Not authenticated');
      const data = await res.json();
      setCurrentUser({ id: data.id, email: data.email });
    } catch (e) {
      storeToken(null);
      setCurrentUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCurrentUser();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function signup(email, password) {
    const res = await fetch(API_BASE + '/register.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Registration failed');
    return data;
  }

  async function login(email, password) {
    const res = await fetch(API_BASE + '/login.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const data = await res.json();
    if (!res.ok || !data.token) throw new Error(data.error || 'Login failed');
    storeToken(data.token);
    await fetchCurrentUser();
    return data;
  }

  async function logout() {
    storeToken(null);
    setCurrentUser(null);
  }

  const value = {
    currentUser,
    signup,
    login,
    logout
  };

  return (
    <AuthContext.Provider value={value}>
      {!loading && children}
    </AuthContext.Provider>
  );
}
