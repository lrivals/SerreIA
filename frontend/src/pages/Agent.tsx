// Agent (docs/12 §2.7, docs/11): list of conversations and the chat (components/ChatAgent).
import { MessageSquarePlus } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useConversations } from "@/api/hooks";
import { ChatAgent } from "@/components/ChatAgent";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export { turnsOf, type Part, type Turn } from "@/components/ChatAgent";

export function Agent() {
  const [params, setParams] = useSearchParams();
  const conversationId = params.get("conversation");
  const list = useConversations();

  return (
    <div className="grid h-[calc(100vh-7rem)] gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="hidden flex-col overflow-hidden lg:flex">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-semibold">Conversations</span>
          <Button size="icon" variant="ghost" title="Nouvelle conversation" onClick={() => setParams({})}>
            <MessageSquarePlus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {list.data?.map((c) => (
            <button
              key={c.id}
              onClick={() => setParams({ conversation: c.id })}
              className={cn("block w-full cursor-pointer border-b px-3 py-2 text-left text-sm hover:bg-muted", c.id === conversationId && "bg-muted")}
            >
              <div className="line-clamp-2">{c.titre || c.id}</div>
              <div className="text-xs text-muted-foreground">
                {fmtDateTime(c.ts_maj)} · {c.tokens?.toLocaleString("fr-FR")} tokens
              </div>
            </button>
          ))}
        </div>
      </Card>
      <ChatAgent
        conversationId={conversationId}
        onConversation={(id) => setParams({ conversation: id }, { replace: true })}
        messageInitial={params.get("message") ?? ""}
      />
    </div>
  );
}
