// ============================================================================
// Firebase Configuration for GitHub Pages & Cloud Pub/Sub Printing
// ============================================================================
// Paste your Firebase Web App configuration below.
// This file is ignored by Git to keep your API keys private.
// ============================================================================

const firebaseConfig = {
    apiKey: "YOUR_API_KEY",
    authDomain: "printer-thing-cc57d.firebaseapp.com",
    projectId: "printer-thing-cc57d",
    storageBucket: "printer-thing-cc57d.firebasestorage.app",
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
