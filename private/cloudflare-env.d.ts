declare namespace Cloudflare {
  interface Env {
    STOCK_AI_PORTFOLIO_OWNER_ID?: string;
    STOCK_AI_PORTFOLIO_TOKEN_SHA256?: string;
    DB?: D1Database;
    BUCKET?: R2Bucket;
  }
}
