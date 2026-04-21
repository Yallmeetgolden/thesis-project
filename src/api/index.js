import axios from 'axios';

const axiosInstance = axios.create({
  baseURL: 'https://kpily-api.azurewebsites.net/v1/'
});

axiosInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken');
  if (token) {
    config.headers = {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  }
  return config;
});

axiosInstance.interceptors.response.use(
  async (response) => {
    return response;
  },
  function (error) {
    if (error.response.status === 401) {
      return Promise.reject(new Error(error.response.data.message));
    } else if (error.response.status === 504) {
      return Promise.reject(new Error('Network timeout try again'));
    }
    return Promise.reject(error);
  }
);

export default axiosInstance;
