`timescale 1ns/1ps
// 标准答案：取自队友 Booth FPGA 工程 booth_modules.v（未改动）
module weighted_sum(input wire clk,rst,
    input wire signed [31:0] pp0_q20,pp1_q20,
    output wire signed [31:0] unscaled_q20,
    output reg signed [31:0] inverting_sum_q20=0,
    output reg signed [31:0] product_q20=0);
    reg signed [27:0] numerator=0;
    reg [26:0] rounded_magnitude=0,quotient=0;
    reg negative=0,negative_delayed=0;
    wire signed [27:0] u=unscaled_q20[27:0];
    assign unscaled_q20=pp0_q20+(pp1_q20<<<2);
    // 400k/888.8889k ~=9/20, 400k/222.2222k ~=9/5.
    // The rounded resistor ratios are represented by exact intended 9/20.
    always @(posedge clk) begin
        if(rst) begin
            numerator<=0; rounded_magnitude<=0; quotient<=0;
            negative<=0; negative_delayed<=0;
            inverting_sum_q20<=0; product_q20<=0;
        end
        else begin
            numerator<=(u<<<3)+u;
            rounded_magnitude<=(numerator[27] ? -numerator : numerator)+28'd10;
            negative<=numerator[27];
            quotient<=rounded_magnitude/28'd20;
            negative_delayed<=negative;
            inverting_sum_q20<=negative_delayed ? $signed({4'b0,quotient}) : -$signed({4'b0,quotient});
            product_q20<=-inverting_sum_q20;
        end
    end
endmodule
