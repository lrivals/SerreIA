import type { ConversationDetail } from "@/api/types";
import { turnsOf } from "./Agent";

test("stored conversation → chat turns", () => {
  const c: ConversationDetail = {
    id: "conv-1",
    titre: "",
    utilisateur: "ui",
    modele: "m",
    ts_debut: "",
    ts_maj: "",
    messages: [
      { role: "user", content: "Allume les LED" },
      {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "…" },
          { type: "text", text: "Je propose :" },
          { type: "tool_use", id: "t1", name: "proposer_action", input: { actionneur: "led" } },
        ],
      },
      {
        role: "user",
        content: [{ type: "tool_result", tool_use_id: "t1", content: '{"proposition": {"id": "dec-20261012-0231-z1-agent1"}}' }],
      },
      { role: "assistant", content: [{ type: "text", text: "À valider." }] },
    ],
    propositions: [{ decision_id: "dec-20261012-0231-z1-agent1", outil: "proposer_action", statut: "proposee" }],
  };
  const turns = turnsOf(c);
  expect(turns).toHaveLength(2);
  expect(turns[0]).toEqual({ role: "user", text: "Allume les LED" });
  const a = turns[1];
  expect(a.role === "assistant" && a.parts.map((p) => p.kind)).toEqual(["text", "tool", "proposition", "text"]);
});
