import { GoogleLogin } from '@react-oauth/google';

const GoogleLoginButton = ({ onSuccess }) => {
  return (
    <GoogleLogin 
      onSuccess={onSuccess}
      onError={() => console.log('Login Failed')}
    />
  );
};

export default GoogleLoginButton;
