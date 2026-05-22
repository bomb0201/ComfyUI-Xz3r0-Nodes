import {
    BaseElement,
    registerCustomElement,
} from '../core/base-element.js?v=20260403-2';

export class XdhButton extends BaseElement {
    static get observedAttributes() {
        return ['variant', 'disabled', 'icon'];
    }

    constructor() {
        super();
    }

    attributeChangedCallback(name, oldValue, newValue) {
        if (oldValue !== newValue && this.shadowRoot) {
            this.renderRoot();
        }
    }

    render() {
        const variant = this.getAttribute('variant') || 'primary';
        const disabled = this.hasAttribute('disabled');
        const icon = this.getAttribute('icon');

        return `
            <style>
                button {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: var(--xdh-space-xs);
                    padding: var(--xdh-space-sm) var(--xdh-space-base);
                    font: var(--xdh-font-button-sm);
                    border: none;
                    border-radius: var(--xdh-radius-sm);
                    cursor: pointer;
                    transition: all 0.15s ease;
                    outline: none;
                }

                button:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }

                button.primary {
                    background: var(--xdh-clr-primary);
                    color: var(--xdh-clr-on-primary);
                    box-shadow: var(--xdh-shadow-default);
                }

                button.primary:hover:not(:disabled) {
                    background: var(--xdh-clr-primary-active);
                    box-shadow: var(--xdh-shadow-popup);
                    transform: translateY(-1px);
                }

                button.secondary {
                    background: var(--xdh-clr-surface-card);
                    color: var(--xdh-clr-ink);
                    border: 1px solid var(--xdh-clr-hairline);
                }

                button.secondary:hover:not(:disabled) {
                    background: var(--xdh-clr-surface-strong);
                }

                @container (max-width: 300px) {
                    .text-label {
                        display: none;
                    }
                }
            </style>
            <button class="${variant}" ${disabled ? 'disabled' : ''}>
                ${icon ? `<span>${icon}</span>` : ''}
                <span class="text-label"><slot></slot></span>
            </button>
        `;
    }
}

registerCustomElement('xdh-button', XdhButton);
