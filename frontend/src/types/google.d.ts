// Google Identity Services types
declare namespace google {
  namespace accounts {
    namespace id {
      interface GsiButtonConfiguration {
        type?: 'standard' | 'icon';
        theme?: 'outline' | 'filled_blue' | 'filled_black';
        size?: 'large' | 'medium' | 'small';
        text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
        shape?: 'rectangular' | 'pill' | 'circle' | 'square';
        logo_alignment?: 'left' | 'center';
        width?: number;
        locale?: string;
      }

      interface CredentialResponse {
        credential: string;
        select_by: string;
      }

      interface PromptMomentNotification {
        isDisplayMoment: () => boolean;
        isDisplayed: () => boolean;
        isNotDisplayed: () => boolean;
        getNotDisplayedReason: () => string;
        isSkippedMoment: () => boolean;
        getSkippedReason: () => string;
        isDismissedMoment: () => boolean;
        getDismissedReason: () => string;
        getMomentType: () => string;
      }

      function initialize(config: {
        client_id: string;
        callback: (response: CredentialResponse) => void;
        auto_select?: boolean;
        cancel_on_tap_outside?: boolean;
        context?: string;
        itp_support?: boolean;
        use_fedcm_for_prompt?: boolean;
      }): void;

      function prompt(
        momentListener?: (notification: PromptMomentNotification) => void
      ): void;

      function renderButton(
        parent: HTMLElement,
        options: GsiButtonConfiguration
      ): void;

      function disableAutoSelect(): void;
      function storeCredential(credential: { id: string; password: string }): void;
      function cancel(): void;
      function revoke(hint: string, callback: () => void): void;
    }
  }
}
