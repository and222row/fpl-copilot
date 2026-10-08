import { NativeTabs } from 'expo-router/unstable-native-tabs';

import { useTheme } from '@/hooks/use-theme';

// Five tabs, the most iOS and Material guidelines allow. Planner and News will
// open from Transfers and Home rather than taking tabs of their own.
export default function TabsLayout() {
  const theme = useTheme();
  return (
    <NativeTabs
      backgroundColor={theme.background}
      indicatorColor={theme.backgroundElement}
      labelStyle={{ selected: { color: theme.text } }}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="house.fill" md="home" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="team">
        <NativeTabs.Trigger.Label>My Team</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="sportscourt.fill" md="stadium" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="transfers">
        <NativeTabs.Trigger.Label>Transfers</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="arrow.left.arrow.right" md="swap_horiz" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="players">
        <NativeTabs.Trigger.Label>Players</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="magnifyingglass" md="search" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="profile">
        <NativeTabs.Trigger.Label>Profile</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="person.crop.circle" md="account_circle" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
