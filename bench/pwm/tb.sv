`timescale 1ns/1ps
// 自检测试台：PERIOD=10 和 PERIOD=256 两个实例，逐周期比对；duty 在周期中途随机变化。
module tb_pwm;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1; reg [7:0] duty = 0;
    wire o10, s10, o256, s256;
    pwm #(.PERIOD(10))  u10 (.clk(clk), .rst(rst), .duty(duty), .pwm_out(o10),  .period_start(s10));
    pwm #(.PERIOD(256)) u256(.clk(clk), .rst(rst), .duty(duty), .pwm_out(o256), .period_start(s256));
    integer n = 0, errors = 0, k, d10 = 0, d256 = 0, c10, c256;
    reg e_o10, e_s10, e_o256, e_s256;
    always @(posedge clk) if (!rst) begin
        c10 = n % 10; c256 = n % 256;
        if (c10 == 0) d10 = duty;
        if (c256 == 0) d256 = duty;
        e_s10 = (c10 == 0); e_o10 = (c10 < d10);
        e_s256 = (c256 == 0); e_o256 = (c256 < d256);
        n = n + 1;
        #1;
        if (o10 !== e_o10 || s10 !== e_s10 || o256 !== e_o256 || s256 !== e_s256) begin
            errors = errors + 1;
            if (errors < 10) $display("TB_FAIL edge %0d duty=%0d: P10 expected out=%b start=%b got %b %b | P256 expected out=%b start=%b got %b %b",
                n - 1, duty, e_o10, e_s10, o10, s10, e_o256, e_s256, o256, s256);
        end
    end
    initial begin
        repeat (2) @(posedge clk); #1;
        if (o10 !== 0 || s10 !== 0) begin errors = errors + 1; $display("TB_FAIL reset outputs"); end
        @(negedge clk); rst = 0; duty = 8'd3;
        for (k = 0; k < 400; k = k + 1) begin
            @(negedge clk);
            if (k % 7 == 0) duty = $random;
            if (k % 50 == 0) duty = 8'd0;
            if (k % 50 == 25) duty = 8'd255;
        end
        for (k = 0; k < 6; k = k + 1) begin
            duty = (k * 51); repeat (256) @(negedge clk);
        end
        if (errors == 0) $display("TB_PASS pwm: %0d edges, two PERIOD settings", n);
        else $display("TB_FAIL pwm: %0d errors", errors);
        $finish;
    end
endmodule
