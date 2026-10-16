import { render, screen, userEvent } from '@testing-library/react-native';
import { Text } from 'react-native';

const mockPush = jest.fn();
const mockBrowser = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-router', () => ({ router: { push: (...a: unknown[]) => mockPush(...a) }, Stack: { Screen: () => null } }));
jest.mock('expo-web-browser', () => ({ openBrowserAsync: (...a: unknown[]) => mockBrowser(...a) }));

import { Carousel } from '@/components/carousel';
import Welcome from '@/app/onboarding';

beforeEach(() => {
  mockPush.mockReset();
  mockBrowser.mockReset();
});

test('a carousel shows every page with a dot each, and a dot selects its page', async () => {
  const user = userEvent.setup();
  await render(<Carousel pages={[<Text key="a">First</Text>, <Text key="b">Second</Text>]} />);
  expect(screen.getByText('First')).toBeTruthy();
  expect(screen.getByText('Second')).toBeTruthy();
  const second = screen.getByLabelText('Show page 2');
  expect(second.props.accessibilityState.selected).toBe(false);
  await user.press(second);
  expect(screen.getByLabelText('Show page 2').props.accessibilityState.selected).toBe(true);
});

test('a single page has no dots', async () => {
  await render(<Carousel pages={[<Text key="a">Only</Text>]} />);
  expect(screen.queryByLabelText('Show page 1')).toBeNull();
});

test('onboarding explains the Team ID, and that a quick code starts the trial', async () => {
  const user = userEvent.setup();
  await render(<Welcome />);
  expect(screen.getAllByText('Find your Team ID')).toHaveLength(2); // the summary and its slide
  expect(screen.getByText(/the number after \/entry\/ in the address bar/i)).toBeTruthy();
  expect(screen.getByText('Your team connects straight away.')).toBeTruthy();
  expect(screen.getByText("A quick code proves it's yours")).toBeTruthy();
  // The trial waits for proof; the slides must not promise it on connect.
  expect(screen.getByText('It starts once a quick code proves the team is yours.')).toBeTruthy();
  expect(screen.queryByText(/moment it is connected/)).toBeNull();
  expect(screen.getByText(/the FPL app cannot rename a team/)).toBeTruthy();
  expect(screen.getByText('Scroll to Admin and tap Team Details.')).toBeTruthy();
  expect(screen.queryByText(/of 4/)).toBeNull();

  await user.press(screen.getByText('Open the FPL website'));
  expect(mockBrowser).toHaveBeenCalledWith('https://fantasy.premierleague.com/');

  await user.press(screen.getByText('Connect my team'));
  expect(mockPush).toHaveBeenCalledWith('/onboarding/team-id');
});
