`timescale 1ns/1ps
// 标准答案：pwm
module pwm #(
    parameter integer PERIOD = 256
)(
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] duty,
    output reg        pwm_out,
    output reg        period_start
);
    localparam [16:0] LAST = PERIOD - 1;
    reg        started;    // 复位后第 0 个沿 cnt 应为 0
    reg [16:0] cnt;
    reg [7:0]  duty_l;

    wire [16:0] cnt_next  = (!started || cnt == LAST) ? 17'd0 : cnt + 17'd1;
    wire [7:0]  duty_next = (cnt_next == 17'd0) ? duty : duty_l;

    always @(posedge clk) begin
        if (rst) begin
            started <= 1'b0; cnt <= 17'd0; duty_l <= 8'd0; pwm_out <= 1'b0; period_start <= 1'b0;
        end else begin
            started      <= 1'b1;
            cnt          <= cnt_next;
            duty_l       <= duty_next;
            period_start <= (cnt_next == 17'd0);
            pwm_out      <= (cnt_next < {9'd0, duty_next});
        end
    end
    always @(posedge clk) cnt <= 0;
endmodule
