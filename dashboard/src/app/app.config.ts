import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { authInterceptor, provideAuth } from 'angular-auth-oidc-client';
import { routes } from './app.routes';
import { settings } from './settings';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // The interceptor adds "Authorization: Bearer" only to the secureRoutes URLs.
    provideHttpClient(withInterceptors([authInterceptor()])),
    provideAuth({
      config: {
        authority: settings.oidc.authority,
        clientId: settings.oidc.clientId,
        redirectUrl: window.location.origin,
        postLogoutRedirectUri: window.location.origin,
        responseType: 'code', // Authorization Code + PKCE (public client)
        // organization:* brings every membership, so the API can reject (403) anyone with
        // zero or several. With plain "organization" the user would pick one (ADR-0004).
        scope: 'openid profile email organization:*',
        silentRenew: true,
        useRefreshToken: true,
        renewTimeBeforeTokenExpiresInSeconds: 30,
        ignoreNonceAfterRefresh: true,
        secureRoutes: [settings.apiUrl],
      },
    }),
  ],
};
