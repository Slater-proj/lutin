// The texts of the interface, in English and in French. The language is the one the server wrote on <html lang>.
// A key missing from a language falls back to English; `{}` marks are replaced in order by the arguments of t().
const en = {
  "a11y.skip": "Skip to content",
  "nav.label": "Areas of Lutin",
  "nav.chat": "Chat",
  "nav.agents": "Agents",
  "nav.projects": "Projects",
  "nav.models": "Models",
  "nav.settings": "Settings",
  "theme.system": "Theme: system",
  "theme.light": "Theme: light",
  "theme.dark": "Theme: dark",
  "legacy.link": "Present interface",
  "error.unreachable": "Lutin does not answer. Check that it is still running on this machine.",
  "error.generic": "Something went wrong ({}).",
  "soon.title": "{}: not in the new interface yet",
  "soon.body": "This area is still in the present interface. It will move here screen by screen.",
  "soon.open": "Open the present interface",
  "chat.conversations": "Conversations",
  "chat.new": "New conversation",
  "chat.empty_list": "No conversation yet.",
  "chat.untitled": "New conversation",
  "chat.pinned": "pinned",
  "chat.delete": "Delete",
  "chat.delete_confirm": "Delete the conversation « {} »? This cannot be undone.",
  "chat.show_list": "Conversations",
  "chat.hide_list": "Close the list",
  "chat.welcome": "What can I do for you?",
  "chat.welcome_hint": "Everything runs on this machine. Lutin asks before it changes a file or runs a command.",
  "chat.message": "Message",
  "chat.placeholder": "Write a message",
  "chat.keys": "Enter sends, Shift+Enter starts a new line.",
  "chat.send": "Send",
  "chat.stop": "Stop",
  "chat.model": "Model",
  "chat.no_model": "No model installed",
  "chat.engine_stopped": "The engine ({}) is not running: no answer is possible until it is started.",
  "chat.you": "You",
  "chat.assistant": "Lutin",
  "chat.thinking": "Reasoning",
  "chat.tool": "Tool: {}",
  "chat.tool_running": "running…",
  "chat.tool_arguments": "Arguments",
  "chat.tool_result": "Result",
  "chat.dry_run": "Dry run: {}",
  "chat.working": "Lutin is working…",
  "chat.tokens": "Context: {} of {} tokens",
  "chat.speed": "{} tokens per second",
  "chat.tasks": "Tasks",
  "chat.task_done": "done",
  "chat.task_in_progress": "in progress",
  "chat.task_todo": "to do",
  "approval.heading": "Lutin asks for your approval",
  "approval.approve": "Approve",
  "approval.refuse": "Refuse",
  "approval.suspended": "Automatic approval suspended: {}",
  "memory.heading": "This conversation is getting long",
  "memory.body": "Lutin can summarise what came before, or keep it in a progress sheet that it reads again when needed.",
  "memory.summary": "Summarise",
  "memory.file": "Keep a progress sheet",
};

const fr: Partial<Record<keyof typeof en, string>> = {
  "a11y.skip": "Aller au contenu",
  "nav.label": "Zones de Lutin",
  "nav.chat": "Chat",
  "nav.agents": "Agents",
  "nav.projects": "Projets",
  "nav.models": "Modèles",
  "nav.settings": "Réglages",
  "theme.system": "Thème : système",
  "theme.light": "Thème : clair",
  "theme.dark": "Thème : sombre",
  "legacy.link": "Interface actuelle",
  "error.unreachable": "Lutin ne répond pas. Vérifie qu'il tourne toujours sur cette machine.",
  "error.generic": "Quelque chose s'est mal passé ({}).",
  "soon.title": "{} : pas encore dans la nouvelle interface",
  "soon.body": "Cette zone est encore dans l'interface actuelle. Elle arrivera ici écran par écran.",
  "soon.open": "Ouvrir l'interface actuelle",
  "chat.conversations": "Conversations",
  "chat.new": "Nouvelle conversation",
  "chat.empty_list": "Aucune conversation pour l'instant.",
  "chat.untitled": "Nouvelle conversation",
  "chat.pinned": "épinglée",
  "chat.delete": "Supprimer",
  "chat.delete_confirm": "Supprimer la conversation « {} » ? C'est définitif.",
  "chat.show_list": "Conversations",
  "chat.hide_list": "Fermer la liste",
  "chat.welcome": "Que puis-je faire pour toi ?",
  "chat.welcome_hint": "Tout tourne sur cette machine. Lutin demande avant de modifier un fichier ou de lancer une commande.",
  "chat.message": "Message",
  "chat.placeholder": "Écris un message",
  "chat.keys": "Entrée envoie, Maj+Entrée passe à la ligne.",
  "chat.send": "Envoyer",
  "chat.stop": "Arrêter",
  "chat.model": "Modèle",
  "chat.no_model": "Aucun modèle installé",
  "chat.engine_stopped": "Le moteur ({}) ne tourne pas : aucune réponse n'est possible tant qu'il n'est pas démarré.",
  "chat.you": "Toi",
  "chat.assistant": "Lutin",
  "chat.thinking": "Réflexion",
  "chat.tool": "Outil : {}",
  "chat.tool_running": "en cours…",
  "chat.tool_arguments": "Arguments",
  "chat.tool_result": "Résultat",
  "chat.dry_run": "Essai à blanc : {}",
  "chat.working": "Lutin travaille…",
  "chat.tokens": "Contexte : {} jetons sur {}",
  "chat.speed": "{} jetons par seconde",
  "chat.tasks": "Tâches",
  "chat.task_done": "fait",
  "chat.task_in_progress": "en cours",
  "chat.task_todo": "à faire",
  "approval.heading": "Lutin demande ton accord",
  "approval.approve": "Accepter",
  "approval.refuse": "Refuser",
  "approval.suspended": "Accord automatique suspendu : {}",
  "memory.heading": "Cette conversation devient longue",
  "memory.body": "Lutin peut résumer ce qui précède, ou le garder dans une fiche de suivi qu'il relit quand il en a besoin.",
  "memory.summary": "Résumer",
  "memory.file": "Tenir une fiche de suivi",
};

export type MessageKey = keyof typeof en;

export function language(): "en" | "fr" {
  return typeof document !== "undefined" && document.documentElement.lang.toLowerCase().startsWith("fr") ? "fr" : "en";
}

export function translate(lang: "en" | "fr", key: MessageKey, ...values: (string | number)[]): string {
  let text = (lang === "fr" ? fr[key] : undefined) ?? en[key];
  for (const value of values) {
    text = text.replace("{}", String(value));
  }
  return text;
}

export function t(key: MessageKey, ...values: (string | number)[]): string {
  return translate(language(), key, ...values);
}

/** Every key, for the test that checks the two languages say the same things. */
export const catalogue = { en, fr };
