package jp.stockai.app;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override public void onCreate(android.os.Bundle savedInstanceState) {
        registerPlugin(StockAIPlugin.class);
        registerPlugin(ChatGPTPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
