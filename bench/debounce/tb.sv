`timescale 1ns/1ps
// 自检测试台：N=4 和 N=37 两个实例，抖动输入，逐周期比对参考模型。
module tb_debounce;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, din = 0;
    wire d4, r4, f4, d37, r37, f37;
    debounce #(.N(4))  u4 (.clk(clk), .rst(rst), .din(din), .dout(d4),  .rise(r4),  .fall(f4));
    debounce #(.N(37)) u37(.clk(clk), .rst(rst), .din(din), .dout(d37), .rise(r37), .fall(f37));
    reg a1 = 0, a2 = 0, ad = 0, ar = 0, af = 0; integer ac = 0;
    reg b1 = 0, b2 = 0, bd = 0, br = 0, bf = 0; integer bc = 0;
    integer errors = 0, k, j, edges = 0, toggles = 0;
    always @(posedge clk) begin
        if (rst) begin a1 <= 0; a2 <= 0; ad <= 0; ac <= 0; ar <= 0; af <= 0;
                       b1 <= 0; b2 <= 0; bd <= 0; bc <= 0; br <= 0; bf <= 0; end
        else begin
            a1 <= din; a2 <= a1; ar <= 0; af <= 0;
            if (a2 == ad) ac <= 0; else if (ac == 3) begin ad <= a2; ac <= 0; ar <= a2; af <= ~a2; end else ac <= ac + 1;
            b1 <= din; b2 <= b1; br <= 0; bf <= 0;
            if (b2 == bd) bc <= 0; else if (bc == 36) begin bd <= b2; bc <= 0; br <= b2; bf <= ~b2; end else bc <= bc + 1;
        end
    end
    always @(negedge clk) begin
        edges = edges + 1;
        if (r4) toggles = toggles + 1;
        if ({d4, r4, f4} !== {ad, ar, af} || {d37, r37, f37} !== {bd, br, bf}) begin
            errors = errors + 1;
            if (errors < 10) $display("TB_FAIL t=%0t N=4 expected %b%b%b got %b%b%b | N=37 expected %b%b%b got %b%b%b",
                $time, ad, ar, af, d4, r4, f4, bd, br, bf, d37, r37, f37);
        end
    end
    initial begin
        repeat (3) @(posedge clk); #2 rst = 0;
        for (k = 0; k < 60; k = k + 1) begin
            for (j = 0; j < 12; j = j + 1) begin #(1.37 + ($random & 15)); din = $random; end   // 抖动；小数偏移避免和时钟沿同时刻
            #3; din = k[0];
            repeat ((k % 5) * 12 + 2) @(posedge clk);                                          // 稳定一段
        end
        repeat (100) @(posedge clk);
        if (toggles == 0) begin errors = errors + 1; $display("TB_FAIL output never rose"); end
        if (errors == 0) $display("TB_PASS debounce: %0d cycles, %0d rising edges (N=4)", edges, toggles);
        else $display("TB_FAIL debounce: %0d errors", errors);
        $finish;
    end
endmodule
