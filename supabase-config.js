// Supabase の設定（アカウント・進捗のサーバー保存に使う）
// 空のままなら、進捗はブラウザ内だけに保存される（アカウント機能はオフ）。
// anonKey は公開して問題ないキー（データは supabase/schema.sql の行レベルセキュリティで本人だけに制限）。
window.SUPABASE_CONFIG = {
  url: "",      // 例: "https://xxxx.supabase.co"
  anonKey: ""   // 例: "eyJhbGciOi..."
};
