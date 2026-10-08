import { StyleSheet, View } from 'react-native';

import { ExternalLink } from '@/components/external-link';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { config } from '@/lib/config';

export function LegalLinks() {
  return (
    <View style={styles.row}>
      {config.termsUrl ? (
        <ExternalLink href={config.termsUrl}>
          <ThemedText type="link" themeColor="textSecondary">
            Terms of Service
          </ThemedText>
        </ExternalLink>
      ) : null}
      {config.privacyUrl ? (
        <ExternalLink href={config.privacyUrl}>
          <ThemedText type="link" themeColor="textSecondary">
            Privacy Policy
          </ThemedText>
        </ExternalLink>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'center', gap: Spacing.four },
});
