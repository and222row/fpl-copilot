// Expo's default Metro config, plus Sentry's debug IDs so crash reports can be
// matched to the uploaded source maps and read as source, not minified code.
// Harmless when Sentry is not configured.
const { getSentryExpoConfig } = require('@sentry/react-native/metro');

module.exports = getSentryExpoConfig(__dirname);
