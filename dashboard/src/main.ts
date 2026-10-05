import { loadSettings } from './app/settings';

// The deployment's URLs first (VIG-42): the app's modules read them as they load, so the app is
// imported only once they are known.
loadSettings()
  .then(() => import('./bootstrap'))
  .catch((err) => console.error(err));
