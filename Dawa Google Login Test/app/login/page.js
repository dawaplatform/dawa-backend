"use client"
import { useState } from 'react';
import GoogleLoginButton from '../components/GoogleLoginButton';
import axios from 'axios';
import { useRouter } from 'next/navigation';

const Login = () => {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGoogleLoginSuccess = async (response) => {
      setLoading(true);
      console.log(response)
    try {
      // Send the Google token to your Django backend
      const res = await axios.post('http://localhost:8000/api/googlelogin/', {
        google_token: response.credential,
        user_role: "Vendor", // or Client
      });

      if (res.status === 200) {
        // Store the token in localStorage or context
        localStorage.setItem('token', res.data.token);

        // Redirect user to dashboard or home
        router.push('/dashboard');
      }
    } catch (err) {
      setError('Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1>Login</h1>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <GoogleLoginButton onSuccess={handleGoogleLoginSuccess} />
      {loading && <p>Loading...</p>}
    </div>
  );
};

export default Login;
