// ============================================================================
// Firebase Configuration Template for GitHub Pages & Cloud Pub/Sub Printing
// ============================================================================
// Copy this file to firebase-config.js and paste your credentials below.
// ============================================================================

const firebaseConfig = {
    apiKey: "YOUR_API_KEY",
    authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT_ID.firebasestorage.app",
    messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
    appId: "YOUR_APP_ID"
};

const isFirebaseConfigured = Boolean(
    typeof firebase !== 'undefined' &&
    firebaseConfig.apiKey &&
    firebaseConfig.apiKey !== "YOUR_API_KEY" &&
    firebaseConfig.projectId &&
    firebaseConfig.projectId !== "YOUR_PROJECT_ID"
);

if (isFirebaseConfigured) {
    try {
        firebase.initializeApp(firebaseConfig);
        window.db = firebase.firestore();
        console.log("[Firebase] Initialized successfully for Cloud Printing!");
    } catch (e) {
        console.error("[Firebase] Initialization error:", e);
        window.db = null;
    }
} else {
    console.log("[Firebase] Not configured or running in Local Network mode.");
    window.db = null;
}
