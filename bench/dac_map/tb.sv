`timescale 1ns/1ps
// 自检测试台：三组参数（正增益、负增益/反相、不同移位），随机 + 边界输入。
module tb_dac_map;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, in_valid = 0;
    reg signed [15:0] x = 16'bx;
    // 输入先是 x，1 ns 后再给初值：这样 0 时刻之后一定有一次输入变化，always @* 写的组合逻辑会被触发。
    // （SystemVerilog 里声明时的初值不产生事件；如果第一组激励恰好等于初值，always @* 一次都不执行，输出一直是 x。）
    initial #1 begin x = 0; end
    wire [9:0] c0, c1, c2; wire s0, s1, s2, v0, v1, v2;
    dac_map #(.G(32'sd26817),    .O(48'sd536870912), .S(20)) u0(clk, rst, in_valid, x, c0, s0, v0);
    dac_map #(.G(-32'sd31234),   .O(48'sd536870912), .S(20)) u1(clk, rst, in_valid, x, c1, s1, v1);
    dac_map #(.G(32'sd1200000),  .O(-48'sd70368744), .S(31)) u2(clk, rst, in_valid, x, c2, s2, v2);
    integer errors = 0, n = 0, k;
    reg [9:0] e0, e1, e2; reg es0, es1, es2;
    reg [9:0] h0, h1, h2;

    task automatic model(input signed [63:0] g, input signed [63:0] o, input integer s,
                         input signed [15:0] xi, output [9:0] code, output sat);
        reg signed [63:0] acc, y;
        begin
            acc = xi * g + o;
            y = acc >>> s;
            if (y < 0) begin code = 0; sat = 1; end
            else if (y > 1023) begin code = 1023; sat = 1; end
            else begin code = y[9:0]; sat = 0; end
        end
    endtask

    task automatic apply(input signed [15:0] xi);
        begin
            @(negedge clk); x = xi; in_valid = 1;
            model(26817, 536870912, 20, xi, e0, es0);
            model(-31234, 536870912, 20, xi, e1, es1);
            model(1200000, -70368744, 31, xi, e2, es2);
            @(posedge clk); #1;
            n = n + 1;
            if (c0 !== e0 || s0 !== es0 || v0 !== 1'b1) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL G>0: x=%0d expected code=%0d sat=%0d got code=%0d sat=%0d valid=%b", xi, e0, es0, c0, s0, v0);
            end
            if (c1 !== e1 || s1 !== es1) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL G<0: x=%0d expected code=%0d sat=%0d got code=%0d sat=%0d", xi, e1, es1, c1, s1);
            end
            if (c2 !== e2 || s2 !== es2) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL S=31: x=%0d expected code=%0d sat=%0d got code=%0d sat=%0d", xi, e2, es2, c2, s2);
            end
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        #1;
        if (c0 !== 10'd512 || s0 !== 0 || v0 !== 0) begin
            errors = errors + 1; $display("TB_FAIL reset: expected code=512 sat=0 valid=0, got %0d %0d %0d", c0, s0, v0);
        end
        @(negedge clk); rst = 0;
        apply(16'sd0); apply(-16'sd32768); apply(16'sd32767); apply(-16'sd1); apply(16'sd1);
        apply(-16'sd20000); apply(16'sd20000); apply(16'sd17000); apply(-16'sd17000);
        for (k = 0; k < 3000; k = k + 1) apply($random);
        // in_valid = 0 时保持
        @(negedge clk); in_valid = 0; h0 = c0; h1 = c1; h2 = c2; x = 16'sd12345;
        repeat (3) @(posedge clk); #1;
        if (c0 !== h0 || c1 !== h1 || c2 !== h2 || v0 !== 0) begin
            errors = errors + 1; $display("TB_FAIL hold: code changed while in_valid=0 or out_valid stayed 1");
        end
        if (errors == 0) $display("TB_PASS dac_map: %0d vectors x 3 parameter sets", n);
        else $display("TB_FAIL dac_map: %0d errors", errors);
        $finish;
    end
endmodule
