import axios from '.';
import { useMutation } from '@tanstack/react-query';

export const _uploadImage = async (formData) => {
  return await axios.post('org/create-task', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
};

export const useImageUpload = () => {
  const imageUploadMutation = useMutation(_uploadImage);
  return {
    imageUploadMutation
  };
};
