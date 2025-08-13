// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyDp5_qu3Re32H5Gfuc7d6OCHTLVNtx1zNE",
  authDomain: "encuesta-f56cd.firebaseapp.com",
  projectId: "encuesta-f56cd",
  storageBucket: "encuesta-f56cd.firebasestorage.app",
  messagingSenderId: "549645219933",
  appId: "1:549645219933:web:cb5653f717e92a2698b5b4",
  measurementId: "G-ZSMWJ5VCFN"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);