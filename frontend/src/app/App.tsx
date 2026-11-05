import { App as LegacyApp } from '../features/legacy/LegacyApp';
import { NewsletterApp } from '../features/newsletter/NewsletterApp';

export function App() {
  return new URLSearchParams(location.search).get('legacy') === '1' ? <LegacyApp /> : <NewsletterApp />;
}
