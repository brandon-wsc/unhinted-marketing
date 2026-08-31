import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KeyFormFields } from "@/features/company-settings/components/key-form-fields";
import { EMPTY_BYOK_KEY_FORM } from "@/features/company-settings/byok-helpers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("KeyFormFields", () => {
  it("hides api_base for gemini and lists the gemini type", () => {
    render(
      <KeyFormFields
        idPrefix="byok-add"
        value={{ ...EMPTY_BYOK_KEY_FORM, providerType: "gemini" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("settings.apiKeys.providerType.gemini")).toBeInTheDocument();
    expect(screen.getByText("settings.apiKeys.wizard.geminiKeyHint")).toBeInTheDocument();
    expect(screen.queryByLabelText("settings.apiKeys.wizard.apiBase")).not.toBeInTheDocument();
  });

  it("hides api_base for vertex_ai and lists the type", () => {
    render(
      <KeyFormFields
        idPrefix="byok-add"
        value={{ ...EMPTY_BYOK_KEY_FORM, providerType: "vertex_ai" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("settings.apiKeys.providerType.vertex_ai")).toBeInTheDocument();
    expect(screen.getByText("settings.apiKeys.wizard.vertexKeyHint")).toBeInTheDocument();
    expect(screen.queryByLabelText("settings.apiKeys.wizard.apiBase")).not.toBeInTheDocument();
  });

  it("shows api_base for openai_compatible", () => {
    render(
      <KeyFormFields
        idPrefix="byok-add"
        value={{
          ...EMPTY_BYOK_KEY_FORM,
          providerType: "openai_compatible",
          apiBase: "https://openrouter.ai/api/v1",
        }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByLabelText("settings.apiKeys.wizard.apiBase")).toBeInTheDocument();
  });
});
