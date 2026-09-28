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
    // El interceptor añade "Authorization: Bearer" solo a las URLs de secureRoutes.
    provideHttpClient(withInterceptors([authInterceptor()])),
    provideAuth({
      config: {
        authority: settings.oidc.authority,
        clientId: settings.oidc.clientId,
        redirectUrl: window.location.origin,
        postLogoutRedirectUri: window.location.origin,
        responseType: 'code', // Authorization Code + PKCE (el cliente es público)
        // organization:* trae todas las membresías: la API rechaza con 403 a quien tenga
        // cero o varias. Con "organization" a secas el usuario elegiría una (ADR-0004).
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
