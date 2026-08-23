// ============================================================================
// Firebase Configuration for Guestbook Thermal Cloud Printing
// ============================================================================

const firebaseConfig = {
    apiKey: "AIzaSyCpfXckgoiOA0CHZrWGAwZjTMcWMtVOIyo",
    authDomain: "printer-thing-cc57d.firebaseapp.com",
    projectId: "printer-thing-cc57d",
    storageBucket: "printer-thing-cc57d.firebasestorage.app",
    messagingSenderId: "343119822017",
    appId: "1:343119822017:web:d70062cda1fe88c4d3e840"
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
        console.log("✓ [Firebase] Cloud Queue initialized successfully!");
    } catch (e) {
        console.error("✗ [Firebase] Initialization error:", e);
        window.db = null;
    }
} else {
    console.log("ℹ [Firebase] Running in local server mode.");
    window.db = null;
}
