// Configuración de Firebase
const firebaseConfig = {
  apiKey: "AIzaSyDp5_qu3Re32H5Gfuc7d6OCHTLVNtx1zNE",
  authDomain: "encuesta-f56cd.firebaseapp.com",
  projectId: "encuesta-f56cd",
  storageBucket: "encuesta-f56cd.firebasestorage.app",
  messagingSenderId: "549645219933",
  appId: "1:549645219933:web:cb5653f717e92a2698b5b4",
  measurementId: "G-ZSMWJ5VCFN"
};

// Inicializar Firebase
firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();